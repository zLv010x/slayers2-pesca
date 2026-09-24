"""Modo "aparecer no Parsec": a janela da macro e o overlay aparecem nas capturas de tela.

Normalmente as duas ficam invisíveis para qualquer print (SetWindowDisplayAffinity), assim a
macro nunca se vê por cima do jogo. Só que o Parsec e o OBS também capturam a tela: quem usa o
PC de longe não via nem o overlay nem a janela pescando (parecia que ela tinha minimizado).

Com o modo ligado as duas aparecem, e aqui a macro:
- apaga (pinta de preto) as duas nos prints que ela mesma tira do jogo (`mask_frame`);
- para ler o que fica ATRÁS delas (o menu principal fica embaixo do overlay da party), deixa as
  duas transparentes por um instante (`hidden`).
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable, Iterator

import numpy as np

import window
from window import Rect

MASK_VALUE = 0
HIDE_SETTLE_SEC = 0.15   # o Windows leva ~1 quadro para tirar a janela transparente da tela
HOTBAR = (0.30, 0.88, 0.70, 1.0)          # barra de itens embaixo, no meio (x0, y0, x1, y1)
CAST_POINT_MARGIN = 0.02

_hwnds: tuple[int, ...] = ()
_hidden_depth = 0        # só a thread da pesca entra em hidden()


def set_own_windows(hwnds: Iterable[int]) -> None:
    """Janelas da macro que aparecem nas capturas (vazio = modo desligado)."""
    global _hwnds
    _hwnds = tuple(int(h) for h in hwnds if h)


def active() -> bool:
    return bool(_hwnds)


def own_rects() -> list[Rect]:
    return [r for r in (window.visible_rect(h) for h in _hwnds) if r is not None]


def mask(img: np.ndarray, origin: Rect, rects: Iterable[Rect]) -> np.ndarray:
    """Pinta no print (que começa em `origin` na tela) o pedaço de cada retângulo que cai nele."""
    for r in rects:
        x0, x1 = max(r.x, origin.x) - origin.x, min(r.x + r.w, origin.x + origin.w) - origin.x
        y0, y1 = max(r.y, origin.y) - origin.y, min(r.y + r.h, origin.y + origin.h) - origin.y
        if x0 < x1 and y0 < y1:
            img[y0:y1, x0:x1] = MASK_VALUE
    return img


def mask_frame(img: np.ndarray, origin: Rect) -> np.ndarray:
    if not _hwnds or _hidden_depth:
        return img  # modo desligado (já invisíveis nos prints) ou transparentes agora
    return mask(img, origin, own_rects())


@contextlib.contextmanager
def hidden() -> Iterator[None]:
    """Deixa as janelas da macro transparentes enquanto ela lê/clica o que fica atrás delas."""
    global _hidden_depth
    if not _hwnds:
        yield
        return
    saved: list[tuple[int, int]] = []
    _hidden_depth += 1
    try:
        if _hidden_depth == 1:
            saved = [(h, window.get_alpha(h)) for h in _hwnds]
            for h, _ in saved:
                window.set_alpha(h, 0)
            time.sleep(HIDE_SETTLE_SEC)
        yield
    finally:
        for h, alpha in saved:
            window.set_alpha(h, alpha)
        _hidden_depth -= 1


def _area_rects(cfg: dict) -> dict[str, tuple[float, float, float, float]]:
    import compass  # aqui dentro: o loot carrega o OCR, e o screen importa este módulo
    import loot
    areas = {
        "avisos dos itens": (loot.REGION_X[0], loot.REGION_Y[0], loot.REGION_X[1], loot.REGION_Y[1]),
        "bússola": (compass.STRIP_X[0], compass.STRIP_Y[0], compass.STRIP_X[1], compass.STRIP_Y[1]),
        "hotbar": HOTBAR,
    }
    sa = cfg.get("scan_area")
    if sa:
        areas["barra do minigame"] = (sa["x"], sa["y"], sa["x"] + sa["w"], sa["y"] + sa["h"])
    cp = cfg.get("cast_point")
    if cp:
        m = CAST_POINT_MARGIN
        areas["ponto de lançamento"] = (cp["x"] - m, cp["y"] - m, cp["x"] + m, cp["y"] + m)
    return areas


def covered_areas(win: Rect, game: Rect, cfg: dict) -> list[str]:
    """Partes do jogo que a macro precisa ver e que a janela `win` cobre (modo Parsec)."""
    out = []
    for name, (fx0, fy0, fx1, fy1) in _area_rects(cfg).items():
        ax0, ay0 = game.x + fx0 * game.w, game.y + fy0 * game.h
        ax1, ay1 = game.x + fx1 * game.w, game.y + fy1 * game.h
        if win.x < ax1 and ax0 < win.x + win.w and win.y < ay1 and ay0 < win.y + win.h:
            out.append(name)
    return out
