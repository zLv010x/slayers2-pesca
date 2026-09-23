"""Acha o aviso de coleta do Roblox ("T  Nome do item / Collect") na tela.

O jeito mais confiável de achar é o círculo branco com o "T" escuro dentro:
é pequeno, redondo, e o "T" forma um buraco no meio do branco. O personagem
(que pode ser branco) é uma mancha grande e irregular, sem esse buraco.

Quando o item balança na ponta da vara, esse aviso some e volta, e o jogo zera
o progresso de segurar T. Por isso a coleta precisa saber se ele está na tela.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Região onde o item fica (em volta do personagem, no centro da tela).
REGION_X = (0.30, 0.70)
REGION_Y = (0.20, 0.80)
WHITE_MIN = 215
# Diâmetro do círculo em fração da largura da área do jogo (~1% medido a 2000 px).
DIAM_FRAC = (0.0065, 0.017)
ASPECT = (0.75, 1.33)
FILL = (0.45, 0.85)           # branco / caixa (círculo cheio seria ~0,79 sem o T)
HOLE_FRAC = (0.05, 0.40)      # área do "T" / área do círculo preenchido
HOLE_CENTER_TOL = 0.30        # o "T" fica perto do centro do círculo


@dataclass(frozen=True)
class Prompt:
    x: int
    y: int
    diameter: int


def _hole_ok(comp: np.ndarray) -> bool:
    """O círculo tem um buraco (o "T") perto do meio?"""
    h, w = comp.shape
    padded = cv2.copyMakeBorder(comp, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(flood, mask, (0, 0), 1)
    holes = (flood[1:-1, 1:-1] == 0)
    filled = comp.sum() + holes.sum()
    if filled == 0 or not holes.any():
        return False
    frac = holes.sum() / filled
    if not HOLE_FRAC[0] <= frac <= HOLE_FRAC[1]:
        return False
    ys, xs = np.nonzero(holes)
    return (abs(xs.mean() - (w - 1) / 2) <= HOLE_CENTER_TOL * w
            and abs(ys.mean() - (h - 1) / 2) <= HOLE_CENTER_TOL * h)


def find_collect_prompt(frame: np.ndarray) -> Prompt | None:
    fh, fw = frame.shape[:2]
    x0, x1 = int(REGION_X[0] * fw), int(REGION_X[1] * fw)
    y0, y1 = int(REGION_Y[0] * fh), int(REGION_Y[1] * fh)
    region = frame[y0:y1, x0:x1]
    white = (region.min(axis=2) >= WHITE_MIN).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white)
    dmin, dmax = DIAM_FRAC[0] * fw, DIAM_FRAC[1] * fw
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (dmin <= w <= dmax and dmin <= h <= dmax):
            continue
        if not ASPECT[0] <= w / h <= ASPECT[1]:
            continue
        if not FILL[0] <= area / float(w * h) <= FILL[1]:
            continue
        comp = (labels[y:y + h, x:x + w] == i).astype(np.uint8)
        if _hole_ok(comp):
            return Prompt(int(x0 + x + w // 2), int(y0 + y + h // 2), int(max(w, h)))
    return None
