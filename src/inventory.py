"""Leitura da tela do inventário (menu M → Inventory → Fishing).

A quantidade de cada item fica numa "pílula" branca no canto do quadrado
("x662"). O OCR do Windows erra números curtos, então tentamos dois recortes:
1. só as letras escuras cercadas de branco (quando o desenho do item encosta na pílula);
2. a pílula inteira, em vários tamanhos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

import ocr

COUNT_RE = re.compile(r"^[^0-9]{0,2}(\d{1,5})$")
PILL_WHITE_MIN = 190
LETTER_H_FRAC = (0.12, 0.35)       # altura de uma letra da pílula / altura do quadrado
OCR_SCALES = (4, 6, 3, 8)
# Quadrado sozinho depois de buscar: fundo colorido, bem mais claro que o fundo do menu.
TILE_MIN_BRIGHTNESS = 45
TILE_MIN_SIDE_FRAC = 0.02          # lado mínimo do quadrado em fração da largura do jogo
GRID_MAX_X = 0.74                  # a grade termina antes do painel de detalhes
GRID_MAX_TILES = 12
ACTIVE_TAB_MIN = 120               # medido: aba selecionada ~180, as outras ~25
SEARCH_TEXT_REACH = 1.8            # o texto digitado pode passar do tamanho do "Item name here!"
SEARCH_ICON_RX = re.compile(r"^[QqOo0]\s+")
PLACEHOLDER_RX = re.compile(r"item\s*name", re.IGNORECASE)
CARET_CHARS = "1li"


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


def find_line(lines: list[ocr.Line], pattern: str) -> ocr.Line | None:
    """Primeira linha lida que contém o padrão (sem diferenciar maiúsculas)."""
    rx = re.compile(pattern, re.IGNORECASE)
    return next((line for line in lines if rx.search(line.text)), None)


def _parse_count(text: str) -> int | None:
    clean = text.replace(" ", "").replace("O", "0").replace("o", "0")
    m = COUNT_RE.match(clean)
    return int(m.group(1)) if m else None


def _ocr_count(gray: np.ndarray) -> int | None:
    for scale in OCR_SCALES:
        big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 20, 20, 40, 40, cv2.BORDER_CONSTANT, value=255)
        for line in ocr.read_lines(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR), min_height=1):
            count = _parse_count(line.text)
            if count is not None:
                return count
    return None


def _ink_only(corner: np.ndarray, tile_h: int) -> np.ndarray | None:
    """Imagem limpa (preto no branco) só com as letras escuras cercadas de branco."""
    white = (corner.min(axis=2) >= PILL_WHITE_MIN).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(1 - white, connectivity=4)
    ch, cw = white.shape
    letters = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if x == 0 or y == 0 or x + w >= cw or y + h >= ch:
            continue
        if LETTER_H_FRAC[0] * tile_h <= h <= LETTER_H_FRAC[1] * tile_h:
            letters.append((x, y, w, h, i))
    if not letters:
        return None
    tallest = max(letters, key=lambda b: b[3])
    mid = tallest[1] + tallest[3] / 2
    letters = [b for b in letters if abs(b[1] + b[3] / 2 - mid) <= tallest[3] / 2]
    x0, y0 = min(b[0] for b in letters), min(b[1] for b in letters)
    x1, y1 = max(b[0] + b[2] for b in letters), max(b[1] + b[3] for b in letters)
    img = np.full((y1 - y0, x1 - x0), 255, np.uint8)
    for x, y, w, h, i in letters:
        img[y - y0:y - y0 + h, x - x0:x - x0 + w][labels[y:y + h, x:x + w] == i] = 0
    return img


def _pill(corner: np.ndarray) -> np.ndarray | None:
    white = (corner.min(axis=2) >= PILL_WHITE_MIN).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(white)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, 4]))
    x, y, w, h, _ = stats[i]
    if w < 12 or h < 8:
        return None
    return cv2.cvtColor(corner[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)


def read_count(tile: np.ndarray) -> int | None:
    """Quantidade na pílula do quadrado ("x662" -> 662). None = sem pílula ou não deu para ler."""
    th, tw = tile.shape[:2]
    corner = tile[:int(th * 0.45), int(tw * 0.25):]
    ink = _ink_only(corner, th)
    if ink is not None:
        count = _ocr_count(ink)
        if count is not None:
            return count
    pill = _pill(corner)
    return _ocr_count(pill) if pill is not None else None


def has_bait_badge(tile: np.ndarray) -> bool:
    """O quadrado tem o selo "✓ Bait" embaixo (isca equipada)?"""
    th = tile.shape[0]
    bottom = cv2.cvtColor(tile[int(th * 0.62):, :], cv2.COLOR_BGR2GRAY)
    for scale in (3, 5):
        big = cv2.resize(bottom, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        if any("bait" in line.text.lower() for line in ocr.read_lines(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))):
            return True
    return False


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_search_text(frame: np.ndarray, search: ocr.Line) -> str:
    """O que está escrito na caixa de busca ("" = vazia, mostrando "Item name here!")."""
    fh, fw = frame.shape[:2]
    y0, y1 = max(0, search.y - search.h), min(fh, search.y + 2 * search.h)
    x0, x1 = max(0, search.x - search.h), min(fw, search.x + int(search.w * SEARCH_TEXT_REACH))
    lines = [line.text.strip() for line in ocr.read_lines(frame[y0:y1, x0:x1])]
    text = " ".join(t for t in lines if len(t) > 1)   # pedaço de 1 letra = lupa ("Q") solta
    text = SEARCH_ICON_RX.sub("", text)                # a lupa grudada no texto
    return "" if PLACEHOLDER_RX.search(text) else text


def search_matches(got: str, want: str) -> bool:
    """A caixa mostra `want`? Aceita o cursor piscando no fim, que o OCR lê como "1"/"l"/"|"."""
    g, w = normalize_text(got), normalize_text(want)
    return g == w or (len(g) == len(w) + 1 and g.startswith(w) and g[-1] in CARET_CHARS)


def find_tiles(frame: np.ndarray, search: ocr.Line) -> list[Box]:
    """Quadrados da primeira linha da grade (abaixo da caixa de busca), da esquerda para a direita."""
    fh, fw = frame.shape[:2]
    side = int(search.h * 4.5)
    x0 = max(0, search.x - side // 2)
    y0 = min(fh, search.y + search.h + search.h // 2)
    x1 = min(int(GRID_MAX_X * fw), x0 + side * GRID_MAX_TILES)
    region = frame[y0:min(fh, y0 + int(side * 1.6)), x0:x1]
    if region.size == 0:
        return []
    bright = (cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) >= TILE_MIN_BRIGHTNESS).astype(np.uint8)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(bright)
    min_side = TILE_MIN_SIDE_FRAC * fw
    tiles = [Box(x0 + x, y0 + y, w, h) for x, y, w, h, _ in stats[1:]
             if w >= min_side and h >= min_side and 0.7 <= w / h <= 1.4]
    return sorted(tiles, key=lambda b: b.x)


def is_active_tab(frame: np.ndarray, line: ocr.Line) -> bool:
    """Aba selecionada tem fundo claro em volta do texto; as outras, fundo escuro."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    pad_x, pad_y = max(4, line.h // 2), max(3, line.h // 5)
    around = gray[max(0, line.y - pad_y):line.y + line.h + pad_y, max(0, line.x - pad_x):line.x + line.w + pad_x]
    return around.size > 0 and float(np.median(around)) >= ACTIVE_TAB_MIN
