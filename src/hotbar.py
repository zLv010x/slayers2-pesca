"""Confere se a vara (slot 3 da hotbar) está equipada.

O slot 3 é o do meio da hotbar, que fica centralizada na tela. Quando o item
está equipado, o jogo desenha um disco cinza-claro atrás do ícone; quando não
está, o disco é escuro. Comparamos o anel interno do disco com o fundo em volta.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Raio do disco do slot medido a 2000 px de largura; escala com a largura da janela.
SLOT_RADIUS_AT_2000 = 24
# Só procura o disco na parte de baixo da tela (a hotbar fica colada no rodapé).
SEARCH_TOP_FRAC = 0.86
# Anel interno (entre o ícone e a borda do disco) e anel externo (fundo).
INNER_R = (0.60, 0.90)
OUTER_R = (1.25, 1.60)
# Disco equipado: cinza claro e neutro, bem mais claro que o fundo.
EQUIPPED_MIN_GRAY = 85
EQUIPPED_MIN_CONTRAST = 18
NEUTRAL_MAX_SAT = 40


@dataclass(frozen=True)
class RodCheck:
    equipped: bool
    center_y: int
    inner_gray: float
    outer_gray: float


def _ring_mask(size: int, radius: float, lo: float, hi: float) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[:size, :size]
    d = np.hypot(xx - c, yy - c)
    return (d >= lo * radius) & (d <= hi * radius)


def check_rod(frame: np.ndarray) -> RodCheck:
    """Analisa um print da área do jogo (BGR) e diz se a vara está na mão."""
    h, w = frame.shape[:2]
    radius = SLOT_RADIUS_AT_2000 * w / 2000.0
    half = int(np.ceil(OUTER_R[1] * radius)) + 1
    size = 2 * half + 1
    inner = _ring_mask(size, radius, *INNER_R)
    outer = _ring_mask(size, radius, *OUTER_R)

    cx = w // 2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sat = (frame.max(axis=2).astype(np.int16) - frame.min(axis=2)).astype(np.float32)

    best: RodCheck | None = None
    best_score = -1e9
    for cy in range(max(half, int(h * SEARCH_TOP_FRAC)), h - half, 2):
        win = gray[cy - half:cy + half + 1, cx - half:cx + half + 1]
        in_gray = float(np.median(win[inner]))
        out_gray = float(np.median(win[outer]))
        in_sat = float(np.median(sat[cy - half:cy + half + 1, cx - half:cx + half + 1][inner]))
        equipped = (
            in_gray >= EQUIPPED_MIN_GRAY
            and in_gray - out_gray >= EQUIPPED_MIN_CONTRAST
            and in_sat <= NEUTRAL_MAX_SAT
        )
        score = in_gray - out_gray
        if score > best_score:
            best_score = score
            best = RodCheck(equipped, cy, in_gray, out_gray)
    if best is None:
        return RodCheck(False, -1, 0.0, 0.0)
    return best
