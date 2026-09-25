"""Lê o aviso "Nome do item / xN" que aparece ao lado do personagem ao coletar.

A raridade vem da cor da faixa atrás do nome, as mesmas cores do inventário:
azul = rare, roxo = epic, dourado = legendary, vermelho = mythic.
Cinza (ou nenhuma cor clara) = common. Ver popup_rarity.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Callable

import cv2
import numpy as np

import ocr
from catalog import fix_ocr, normalize, plausible_name

# Reconhecedor opcional de nomes (o catálogo: "esse nome lido é um item conhecido?").
Known = Callable[[str], bool]

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
# Nome partido em duas linhas pelo OCR ("Zebra" + "Fish", "6>Meta" + "Iscraps"): pedaços na
# mesma altura e quase encostados são o mesmo aviso (os avisos se empilham um embaixo do outro).
SPLIT_MAX_GAP = 1.5   # alturas de letra entre o fim de um pedaço e o começo do outro
SPLIT_MAX_DY = 0.5    # diferença entre o meio das duas linhas, em alturas de letra
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

# Cores das raridades: (raridade, faixas de matiz do OpenCV 0-179, S mínima, V mínima).
# Medido nas bordas dos avisos: azul H 103-112, dourado H 17-22 com S 86-180, vermelho
# H 0-5; roxo ~150 (inventário). Ficam de fora a madeira do píer (H 10-13, virava
# "legendary"), a madeira à noite (V ~20) e as bordas bege das comuns (S ~45).
RARITY_COLORS = (
    ("epic", ((135, 165),), 45, 40),
    ("mythic", ((0, 5), (172, 179)), 90, 35),
    ("legendary", ((15, 30),), 75, 55),
    ("rare", ((100, 118),), 45, 40),
)
# Pedaço liso (fundo do quadrado no inventário): precisa de 15%+ de pixels da cor.
MIN_COLOR_FRAC = 0.15

# A faixa do aviso tem duas bordas finas (1-2 px) na cor da raridade, uma acima e outra
# abaixo do nome (~0,65 e ~1,75 altura de letra do topo do nome). O miolo é quase
# transparente: a madeira/água/pedra do fundo aparece nele e enganava a média da faixa.
# "Borda" = fileira com bem mais pixels da cor do que as fileiras EDGE_GAP_PX acima e
# abaixo; fundo liso não forma borda, e a borda continua visível com o aviso apagando.
EDGE_SEARCH_UP = 1.2     # alturas de letra acima do topo da caixa do OCR (caixa às vezes desloca)
EDGE_SEARCH_DOWN = 2.7   # alturas de letra abaixo do topo da caixa
EDGE_GAP_PX = 3
EDGE_SEGMENTS = 3        # a cor some da esquerda para a direita: mede cada terço do nome
EDGE_MIN = 0.4           # fração de pixels da cor acima das fileiras vizinhas
EDGE_ALONE_MIN = 0.7     # borda sem par (a outra sumiu) precisa ser forte: riscos do cenário dão 0,4-0,7
EDGE_PAIR_SPAN = (1.0, 3.0)  # distância entre as duas bordas, em alturas de letra (medido ~2,1-2,4)


@dataclass(frozen=True)
class Loot:
    name: str
    quantity: int
    rarity: str
    box: tuple[int, int, int, int]  # x, y, w, h na imagem inteira
    is_new: bool = False            # primeira vez na coleção (selo amarelo "NEW!")
    lone: bool = False              # só uma das variantes do OCR leu esse nome (desconfiado)


def _parse_qty(text: str) -> int | None:
    m = QTY_RE.match(text.strip())
    if not m:
        return None
    try:
        return int(m.group(1).translate(DIGIT_FIX))
    except ValueError:
        return None


def _color_masks(hsv: np.ndarray) -> dict[str, np.ndarray]:
    """Para cada raridade, os pixels que têm a cor dela."""
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    masks = {}
    for rarity, ranges, min_sat, min_val in RARITY_COLORS:
        in_range = np.zeros(hue.shape, bool)
        for lo, hi in ranges:
            in_range |= (hue >= lo) & (hue <= hi)
        masks[rarity] = in_range & (sat >= min_sat) & (val >= min_val)
    return masks


def classify_rarity(patch_bgr: np.ndarray) -> str:
    """Raridade pela cor dominante de um pedaço liso (ex.: fundo do quadrado no inventário)."""
    best, best_frac = "common", MIN_COLOR_FRAC
    for rarity, mask in _color_masks(cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2HSV)).items():
        frac = float(mask.mean())
        if frac > best_frac:
            best, best_frac = rarity, frac
    return best


def _edge_strength(mask: np.ndarray) -> np.ndarray:
    """Por fileira: quanto ela tem a mais da cor que as fileiras EDGE_GAP_PX acima e abaixo.

    Mede cada terço da largura e fica com o melhor (a borda vai sumindo para a direita).
    """
    gap = EDGE_GAP_PX
    strength = np.zeros(mask.shape[0])
    if mask.shape[0] <= 2 * gap:
        return strength
    for part in np.array_split(mask, EDGE_SEGMENTS, axis=1):
        if part.shape[1] == 0:
            continue
        frac = part.mean(axis=1)
        above_below = np.maximum(frac[:-2 * gap], frac[2 * gap:])
        strength[gap:-gap] = np.maximum(strength[gap:-gap], frac[gap:-gap] - above_below)
    return strength


def _edge_score(strength: np.ndarray, h: int, alone_ok: bool) -> float:
    """Força da borda da faixa: a das duas bordas (cima e baixo) ou uma sozinha bem forte.

    alone_ok: com o selo NEW! a borda de baixo fica escondida, então basta uma.
    """
    rows = np.flatnonzero(strength >= EDGE_MIN)
    if rows.size == 0:
        return 0.0
    lo, hi = EDGE_PAIR_SPAN[0] * h, EDGE_PAIR_SPAN[1] * h
    pair = 0.0
    for r in rows:
        partners = rows[(rows - r >= lo) & (rows - r <= hi)]
        if partners.size:
            pair = max(pair, min(strength[r], strength[partners].max()))
    strongest = float(strength.max())
    alone = strongest if alone_ok or strongest >= EDGE_ALONE_MIN else 0.0
    return max(pair, alone)


def _badge_mask(hsv: np.ndarray, h: int) -> np.ndarray:
    """Pixels do selo amarelo "NEW!" (com uma margem): ele não pode contar como dourado."""
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    badge = ((hue >= NEW_HUE[0]) & (hue <= NEW_HUE[1]) & (sat >= NEW_MIN_SAT)
             & (val >= NEW_MIN_VAL)).astype(np.uint8)
    size = 2 * max(2, h // 6) + 1
    return cv2.dilate(badge, np.ones((size, size), np.uint8)).astype(bool)


def popup_rarity(frame: np.ndarray, box: tuple[int, int, int, int], is_new: bool = False) -> str:
    """Raridade do aviso pelas bordas finas coloridas da faixa atrás do nome.

    box = caixa do nome dada pelo OCR. A busca vai de EDGE_SEARCH_UP alturas acima até
    EDGE_SEARCH_DOWN abaixo do topo dela: a caixa às vezes vem deslocada ou com o ícone junto.
    """
    x, y, w, h = box
    fh, fw = frame.shape[:2]
    x0, x1 = max(0, x), min(fw, x + w)
    y0, y1 = max(0, y - int(EDGE_SEARCH_UP * h)), min(fh, y + int(EDGE_SEARCH_DOWN * h))
    if h <= 0 or x1 - x0 < EDGE_SEGMENTS or y1 - y0 <= 2 * EDGE_GAP_PX:
        return "common"
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    keep = ~_badge_mask(hsv, h) if is_new else np.ones(hsv.shape[:2], bool)
    best, best_score = "common", 0.0
    for rarity, mask in _color_masks(hsv).items():
        score = _edge_score(_edge_strength(mask & keep), h, alone_ok=is_new)
        if score > best_score:
            best, best_score = rarity, score
    return best


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


def _name_key(name: str) -> str:
    return normalize(fix_ocr(name))


def read_popups(frame: np.ndarray, variants=OCR_VARIANTS, best: bool = True,
                known: Known | None = None) -> list[Loot]:
    """Todos os avisos de item visíveis (eles se empilham, um embaixo do outro).

    best=True: roda todas as variantes e fica com a leitura em que o catálogo (known) reconhece
    mais nomes; no empate, a mais completa/limpa. A mais comprida sozinha escolhia lixo:
    "J V uaJZebra Fish" ganhava de "Zebra Fish", "C r LI Stad o II" de "Crustadon".
    Marca `lone` no nome que só uma variante leu.
    best=False: para na primeira variante que achar algo (para checagens rápidas).
    """
    results = []
    for threshold, upscale in variants:
        found = _read_popups_once(frame, threshold, upscale, known=known)
        if found:
            if not best:
                return found
            results.append(found)
    if not results:
        return []
    recognized = (lambda items: sum(1 for i in items if known(i.name))) if known else (lambda items: 0)
    chosen = max(results, key=lambda r: (recognized(r), len(r), _name_score(r)))
    if len(variants) < 2:
        return chosen
    readings = [{_name_key(i.name) for i in r} for r in results]
    return [replace(i, lone=True) if sum(_name_key(i.name) in keys for keys in readings) == 1 else i
            for i in chosen]


def _same_row(left: ocr.Line, right: ocr.Line) -> bool:
    h = max(left.h, right.h)
    gap = right.x - (left.x + left.w)
    dy = abs((left.y + left.h / 2) - (right.y + right.h / 2))
    return -h / 2 <= gap <= SPLIT_MAX_GAP * h and dy <= SPLIT_MAX_DY * h


def _join(left: ocr.Line, right: ocr.Line) -> ocr.Line:
    x0, y0 = min(left.x, right.x), min(left.y, right.y)
    x1 = max(left.x + left.w, right.x + right.w)
    y1 = max(left.y + left.h, right.y + right.h)
    return ocr.Line(f"{left.text} {right.text}", x0, y0, x1 - x0, y1 - y0)


def _should_join(left: ocr.Line, right: ocr.Line, known: Known | None) -> bool:
    """Sem catálogo junta sempre; com ele, não estraga um nome reconhecido com texto do lado."""
    if known is None or known(clean_name(f"{left.text} {right.text}")):
        return True
    return not (known(clean_name(left.text)) or known(clean_name(right.text)))


def _join_split_names(lines: list[ocr.Line], known: Known | None = None) -> list[ocr.Line]:
    """Junta os pedaços de um nome partido em linhas lado a lado (a ordem das linhas fica)."""
    done = [False] * len(lines)
    out = []
    for i, line in enumerate(lines):
        if done[i]:
            continue
        if _parse_qty(line.text) is None:
            for j in range(i + 1, len(lines)):
                other = lines[j]
                if done[j] or _parse_qty(other.text) is not None:
                    continue
                left, right = sorted((line, other), key=lambda item: item.x)
                if _same_row(left, right) and _should_join(left, right, known):
                    line, done[j] = _join(left, right), True
        out.append(line)
    return out


def _read_popups_once(frame: np.ndarray, threshold: int | None, upscale: int,
                      known: Known | None = None) -> list[Loot]:
    fh, fw = frame.shape[:2]
    rx0, rx1 = int(REGION_X[0] * fw), int(REGION_X[1] * fw)
    ry0, ry1 = int(REGION_Y[0] * fh), int(REGION_Y[1] * fh)
    region = frame[ry0:ry1, rx0:rx1]
    lines = ocr.read_lines(_white_text(region, threshold), min_height=upscale * region.shape[0])
    lines = _join_split_names(lines, known)
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
        rarity = popup_rarity(frame, (x, y, line.w, line.h), is_new)
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
