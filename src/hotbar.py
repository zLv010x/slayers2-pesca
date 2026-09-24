"""Confere se a vara (slot 3 da hotbar) está equipada.

O slot 3 é o do meio da hotbar, que fica centralizada na tela. Quando o item
está equipado, o jogo desenha um disco claro (semi-transparente) atrás do ícone.

Comparamos o slot 3 com os vizinhos (slots 2 e 4), que nunca estão destacados
enquanto a vara está na mão: assim o que está atrás da hotbar (deck, grama verde,
água) não engana, porque afeta os três slots igual.
Medido: vara na mão = slot 3 fica 74-82 mais claro que os vizinhos; sem vara, no máximo 9.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Raio do disco do slot e distância entre slots, medidos a 2000 px de largura.
SLOT_RADIUS_AT_2000 = 24
SLOT_STEP_AT_2000 = 70
# Só procura a hotbar na parte de baixo da tela (ela fica colada no rodapé).
SEARCH_TOP_FRAC = 0.86
# Anel entre o ícone e a borda do disco (o ícone no meio atrapalharia a comparação).
INNER_R = (0.60, 0.90)
EQUIPPED_MIN_GRAY = 85
EQUIPPED_MIN_LEAD = 30          # quanto o slot 3 precisa ser mais claro que o vizinho mais claro


@dataclass(frozen=True)
class RodCheck:
    equipped: bool
    center_y: int
    inner_gray: float       # brilho do anel do slot 3
    outer_gray: float       # brilho do vizinho mais claro (slot 2 ou 4)


def _ring_mask(size: int, radius: float, lo: float, hi: float) -> np.ndarray:
    c = (size - 1) / 2.0
    yy, xx = np.mgrid[:size, :size]
    d = np.hypot(xx - c, yy - c)
    return (d >= lo * radius) & (d <= hi * radius)


def check_rod(frame: np.ndarray) -> RodCheck:
    """Analisa um print da área do jogo (BGR) e diz se a vara está na mão."""
    h, w = frame.shape[:2]
    radius = SLOT_RADIUS_AT_2000 * w / 2000.0
    step = int(round(SLOT_STEP_AT_2000 * w / 2000.0))
    half = int(np.ceil(radius)) + 1
    ring = _ring_mask(2 * half + 1, radius, *INNER_R)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def ring_median(cx: int, cy: int) -> float:
        win = gray[cy - half:cy + half + 1, cx - half:cx + half + 1]
        return float(np.median(win[ring]))

    cx = w // 2
    if cx - step - half < 0 or cx + step + half >= w:
        return RodCheck(False, -1, 0.0, 0.0)
    best = RodCheck(False, -1, 0.0, 0.0)
    best_lead = -1e9
    for cy in range(max(half, int(h * SEARCH_TOP_FRAC)), h - half, 2):
        slot3 = ring_median(cx, cy)
        neighbors = max(ring_median(cx - step, cy), ring_median(cx + step, cy))
        lead = slot3 - neighbors
        if lead > best_lead:
            best_lead = lead
            equipped = slot3 >= EQUIPPED_MIN_GRAY and lead >= EQUIPPED_MIN_LEAD
            best = RodCheck(equipped, cy, slot3, neighbors)
    return best
