"""Lê o aviso "Nome do item / xN" que aparece ao lado do personagem ao coletar.

A raridade vem da cor da faixa atrás do nome, as mesmas cores do inventário:
azul = rare, roxo = epic, dourado = legendary, vermelho = mythic.
Cinza (ou nenhuma cor clara) = common.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

import ocr
from catalog import plausible_name

# Área onde o aviso aparece: à direita do personagem, que fica no centro da tela.
REGION_X = (0.49, 0.80)
REGION_Y = (0.25, 0.85)

QTY_RE = re.compile(r"^[^\w]*[xX×]\s*([0-9lIoO]+)\s*$")
# Letras que o OCR confunde com dígitos em "x1", "x10"...
DIGIT_FIX = str.maketrans({"l": "1", "I": "1", "o": "0", "O": "0"})

# Altura para ampliar o recorte do "xN" antes do OCR.
QTY_OCR_HEIGHT = 200
MIN_NAME_LEN = 2
# Quantas alturas de letra o "xN" pode estar para o lado do nome.
QTY_SIDE_REACH = 4
LEADING_STRAY_RX = re.compile(r"^\S\s+(?=\S{3,})")
NAME_EDGE_JUNK = re.compile(r"^[^\w(]+|[^\w)!?]+$")
# Texto dos avisos é branco; ampliar 2x ajuda a ler o "xN" pequeno.
WHITE_TEXT_MIN = 200
OCR_UPSCALE = 2
# Telas menores (1920) deixam o texto menos branco: tenta outras combinações de
# (limite de branco, ampliação) até achar o aviso.
# None = sem limite: cinza invertido (acha aviso apagando/pequeno; ex.: janela 1002x981).
OCR_VARIANTS = ((200, 2), (155, 3), (185, 2), (None, 3))

# Selo amarelo "NEW!" que substitui o "xN" quando o item é novo na coleção.
NEW_HUE = (15, 35)
NEW_MIN_SAT = 150
NEW_MIN_VAL = 170
NEW_MIN_FRAC = 0.12

# Faixa de pixels acima/abaixo do nome onde a cor da raridade aparece.
BAND_PAD = 8
MIN_SAT = 55
MIN_VAL = 60
# Faixa colorida de verdade dá 30%+ de pixels da cor; o brilho bege das comuns dá ~8%.
MIN_COLOR_FRAC = 0.15
# Matizes do OpenCV (0-179), medidas no inventário: azul ~101, roxo ~150,
# dourado ~22, vermelho ~1.
HUE_RANGES = (
    ("epic", ((138, 165),)),
    ("mythic", ((0, 8), (170, 179))),
    ("legendary", ((12, 35),)),
    ("rare", ((95, 130),)),
)


@dataclass(frozen=True)
class Loot:
    name: str
    quantity: int
    rarity: str
    box: tuple[int, int, int, int]  # x, y, w, h na imagem inteira
    is_new: bool = False            # primeira vez na coleção (selo amarelo "NEW!")


def _parse_qty(text: str) -> int | None:
    m = QTY_RE.match(text.strip())
    if not m:
        return None
    try:
        return int(m.group(1).translate(DIGIT_FIX))
    except ValueError:
        return None


def classify_rarity(band_bgr: np.ndarray) -> str:
    """Decide a raridade pela cor dominante dos pixels coloridos da faixa."""
    hsv = cv2.cvtColor(band_bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colored = (sat >= MIN_SAT) & (val >= MIN_VAL)
    total = colored.size
    best, best_frac = "common", MIN_COLOR_FRAC
    for rarity, ranges in HUE_RANGES:
        in_range = np.zeros_like(colored)
        for lo, hi in ranges:
            in_range |= (hue >= lo) & (hue <= hi)
        frac = float((colored & in_range).sum()) / max(total, 1)
        if frac > best_frac:
            best, best_frac = rarity, frac
    return best


def _band(frame: np.ndarray, x: int, y: int, w: int, h: int, top_only: bool = False) -> np.ndarray:
    """Recorta a faixa colorida acima e abaixo do texto, sem o ícone à esquerda."""
    fh, fw = frame.shape[:2]
    x0, x1 = max(0, x), min(fw, x + w)
    top = frame[max(0, y - BAND_PAD):max(0, y - 2), x0:x1]
    bottom = frame[min(fh, y + h + 2):min(fh, y + h + BAND_PAD), x0:x1]
    # Com o selo NEW! embaixo, só a parte de cima mostra a cor da raridade.
    parts = [p for p in ((top,) if top_only else (top, bottom)) if p.size]
    if not parts:
        return frame[max(0, y):min(fh, y + h), x0:x1]
    return np.vstack(parts)


def _read_quantity(frame: np.ndarray, x: int, y: int, w: int, h: int) -> int | None:
    """O "xN" é pequeno: relê só a área logo abaixo do nome, ampliada."""
    fh, fw = frame.shape[:2]
    reach = QTY_SIDE_REACH * h
    crop = frame[max(0, y - h):min(fh, y + 3 * h), max(0, x - reach):min(fw, x + w + reach)]
    if crop.size == 0:
        return None
    # o "xN" é bem pequeno: o limite de branco às vezes apaga ele; aí tenta sem limite
    for threshold in (WHITE_TEXT_MIN, None):
        for line in ocr.read_lines(_white_text(crop, threshold), min_height=QTY_OCR_HEIGHT):
            qty = _parse_qty(line.text)
            if qty is not None and line.y > h // 2:
                return qty
    return None


def _white_text(bgr: np.ndarray, threshold: int | None = WHITE_TEXT_MIN) -> np.ndarray:
    """Deixa só o texto branco (preto sobre branco): o OCR erra muito com o jogo atrás.

    threshold=None: sem limite, só inverte o cinza (texto claro vira escuro).
    """
    if threshold is None:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(255 - gray, cv2.COLOR_GRAY2BGR)
    mask = bgr.min(axis=2) >= threshold
    out = np.full(mask.shape, 255, np.uint8)
    out[mask] = 0
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def has_new_badge(frame: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    """Procura o selo amarelo "NEW!" logo abaixo do nome."""
    fh, fw = frame.shape[:2]
    crop = frame[min(fh, y + h + 1):min(fh, y + int(2.6 * h)), max(0, x):min(fw, x + w)]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yellow = ((hsv[..., 0] >= NEW_HUE[0]) & (hsv[..., 0] <= NEW_HUE[1])
              & (hsv[..., 1] >= NEW_MIN_SAT) & (hsv[..., 2] >= NEW_MIN_VAL))
    return float(yellow.mean()) >= NEW_MIN_FRAC


def clean_name(text: str) -> str:
    """Tira sujeira que o OCR põe nas pontas ("'Zebra Fish" -> "Zebra Fish").

    Também tira uma letra solta no começo: o desenho do item grudado no nome às vezes
    é lido como letra ("U Zebra Fish", "H Zebra Fish").
    """
    name = NAME_EDGE_JUNK.sub("", text).strip()
    return LEADING_STRAY_RX.sub("", name).strip()


def _qty_below(line: ocr.Line, lines: list[ocr.Line]) -> int | None:
    """Acha o "xN" logo abaixo do nome.

    O "xN" fica centralizado na faixa do aviso, não no texto: com nome curto
    ("Coral") ele aparece à DIREITA do nome, então aceitamos um pouco para o lado.
    """
    left = line.x - QTY_SIDE_REACH * line.h
    right = line.x + line.w + QTY_SIDE_REACH * line.h
    for other in lines:
        qty = _parse_qty(other.text)
        if qty is None:
            continue
        below = line.y + line.h // 2 < other.y <= line.y + 3 * line.h
        beside = other.x < right and other.x + other.w > left
        if below and beside:
            return qty
    return None


def _name_score(items: list[Loot]) -> int:
    """Nome "limpo" = muitas letras e nenhum símbolo estranho ('Fisll', 'Fi-.h' perdem)."""
    return sum(len(re.sub(r"[^A-Za-z]", "", i.name)) - 3 * len(re.sub(r"[A-Za-z0-9 ']", "", i.name))
               for i in items)


def read_popups(frame: np.ndarray, variants=OCR_VARIANTS, best: bool = True) -> list[Loot]:
    """Todos os avisos de item visíveis (eles se empilham, um embaixo do outro).

    best=True: roda todas as variantes e fica com a leitura mais completa/limpa.
    best=False: para na primeira variante que achar algo (para checagens rápidas).
    """
    results = []
    for threshold, upscale in variants:
        found = _read_popups_once(frame, threshold, upscale)
        if found:
            if not best:
                return found
            results.append(found)
    if not results:
        return []
    return max(results, key=lambda r: (len(r), _name_score(r)))


def _read_popups_once(frame: np.ndarray, threshold: int | None, upscale: int) -> list[Loot]:
    fh, fw = frame.shape[:2]
    rx0, rx1 = int(REGION_X[0] * fw), int(REGION_X[1] * fw)
    ry0, ry1 = int(REGION_Y[0] * fh), int(REGION_Y[1] * fh)
    region = frame[ry0:ry1, rx0:rx1]
    lines = ocr.read_lines(_white_text(region, threshold), min_height=upscale * region.shape[0])
    found: list[Loot] = []
    for line in lines:
        name = clean_name(line.text)
        if len(name) < MIN_NAME_LEN or _parse_qty(name) is not None or not plausible_name(name):
            continue
        x, y = line.x + rx0, line.y + ry0
        is_new = False
        qty = _qty_below(line, lines)
        if qty is None and has_new_badge(frame, x, y, line.w, line.h):
            qty, is_new = 1, True
        if qty is None:
            qty = _read_quantity(frame, x, y, line.w, line.h)
        if qty is None:
            continue
        rarity = classify_rarity(_band(frame, x, y, line.w, line.h, top_only=is_new))
        found.append(Loot(name, qty, rarity, (x, y, line.w, line.h), is_new))
    return found


def read_popup(frame: np.ndarray) -> Loot | None:
    """O primeiro aviso de item visível, ou None."""
    items = read_popups(frame)
    return items[0] if items else None


def new_items(before: list[Loot], after: list[Loot]) -> list[Loot]:
    """Avisos que apareceram depois de 'before' (conta repetidos: 2x Metal Scraps x4 etc.)."""
    seen = Counter((i.name, i.quantity) for i in before)
    fresh = []
    for item in after:
        key = (item.name, item.quantity)
        if seen[key] > 0:
            seen[key] -= 1
        else:
            fresh.append(item)
    return fresh


def item_snapshot(frame: np.ndarray, loot: Loot) -> np.ndarray:
    """Recorte com o ícone e o nome, para mandar junto no Discord."""
    fh, fw = frame.shape[:2]
    x, y, w, h = loot.box
    x0, y0 = max(0, x - 3 * h), max(0, y - h)
    x1, y1 = min(fw, x + w + h), min(fh, y + 3 * h)
    return frame[y0:y1, x0:x1].copy()
