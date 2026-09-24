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
# O "T" escuro sozinho (medido nos prints e no vídeo, em fração da largura do jogo).
T_W_FRAC = (0.0025, 0.008)
T_H_FRAC = (0.0035, 0.009)
T_FILL = (0.35, 0.70)
T_TOP_MIN = 0.85              # barra de cima ocupa quase toda a largura
T_BOTTOM_MAX = 0.55           # embaixo só a haste
T_STEM_CENTER_TOL = 0.20


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


def _is_t_glyph(glyph: np.ndarray) -> bool:
    """Forma de "T": barra de cima larga e haste estreita no meio embaixo."""
    h, w = glyph.shape
    fill = glyph.sum() / float(w * h)
    if not T_FILL[0] <= fill <= T_FILL[1]:
        return False
    top = glyph[:max(1, h // 4)].any(axis=0).mean()
    bottom_rows = glyph[h * 2 // 3:]
    bottom = bottom_rows.any(axis=0).mean()
    if top < T_TOP_MIN or bottom > T_BOTTOM_MAX:
        return False
    cols = np.nonzero(bottom_rows.any(axis=0))[0]
    return cols.size > 0 and abs(cols.mean() - (w - 1) / 2) <= T_STEM_CENTER_TOL * w


def _find_t_glyph(white: np.ndarray, ref: float) -> tuple[int, int, int] | None:
    """Acha o "T" escuro cercado de branco (serve para círculo e losango, mesmo grudado na vara)."""
    dark = (1 - white).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=4)
    rh, rw = dark.shape
    wmin, wmax = T_W_FRAC[0] * ref, T_W_FRAC[1] * ref
    hmin, hmax = T_H_FRAC[0] * ref, T_H_FRAC[1] * ref
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if x == 0 or y == 0 or x + w >= rw or y + h >= rh:
            continue  # encosta na borda: não está cercado de branco
        if not (wmin <= w <= wmax and hmin <= h <= hmax):
            continue
        if _is_t_glyph(labels[y:y + h, x:x + w] == i):
            return x + w // 2, y + h // 2, int(max(w, h) * 2)
    return None


def find_collect_prompt(frame: np.ndarray) -> Prompt | None:
    fh, fw = frame.shape[:2]
    # O aviso acompanha o FOV vertical do Roblox, não a largura da janela: numa janela
    # estreita (largura menor que 16:9) o aviso fica GRANDE demais para os limites em
    # fração de fw, e o personagem (deslocado do centro) pode cair fora da faixa de
    # busca horizontal. Por isso o tamanho e a região usam a largura "equivalente" a
    # 16:9 calculada a partir da altura, centrada na janela real (que pode ser mais
    # estreita que essa referência).
    ref = fh * 16 / 9
    x_half = (REGION_X[1] - REGION_X[0]) / 2 * ref
    x0 = max(0, int(fw / 2 - x_half))
    x1 = min(fw, int(fw / 2 + x_half))
    y0, y1 = int(REGION_Y[0] * fh), int(REGION_Y[1] * fh)
    region = frame[y0:y1, x0:x1]
    white = (region.min(axis=2) >= WHITE_MIN).astype(np.uint8)
    found = _find_by_shape(white, ref)
    if found is None:
        found = _find_t_glyph(white, ref)
    if found is None:
        return None
    x, y, d = found
    return Prompt(int(x0 + x), int(y0 + y), int(d))


def _find_by_shape(white: np.ndarray, ref: float) -> tuple[int, int, int] | None:
    """Círculo (ou losango) branco pequeno com um buraco no meio."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(white)
    dmin, dmax = DIAM_FRAC[0] * ref, DIAM_FRAC[1] * ref
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
            return x + w // 2, y + h // 2, int(max(w, h))
    return None
