"""Tela do menu principal do jogo (PLAY / CUSTOMIZE / HUB / SLOTS).

Aparece quando o servidor reinicia ou a pessoa cai do jogo (24/09 02:28): sem
personagem, sem vara e sem bússola. Pescar fica impossível até alguém entrar de
novo e voltar ao ponto de pesca, então a macro para e avisa em vez de ficar
tentando (ou pausada esperando a câmera) a noite toda.

O menu fica na mesma área do painel da party (e o relog CLICA no PLAY): por isso
exige 3 das 4 palavras, na ordem do menu de cima para baixo. Nomes da party como
"Play" ou "Hub" não formam isso.
"""
from __future__ import annotations

import re

import numpy as np

import ocr

MENU_WORDS = {"play", "customize", "hub", "slots"}
MIN_WORDS = 3
MENU_ORDER = ("play", "customize", "hub", "slots")  # de cima para baixo
REGION_X = (0.0, 0.16)
REGION_Y = (0.38, 0.62)
# O texto do menu é claro sobre fundo desfocado: o OCR lê melhor sem binarizar, ampliado.
OCR_UPSCALE = 2


def menu_region(frame: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Recorte do painel da esquerda e a origem dele no frame."""
    fh, fw = frame.shape[:2]
    x0, y0 = int(REGION_X[0] * fw), int(REGION_Y[0] * fh)
    return frame[y0:int(REGION_Y[1] * fh), x0:int(REGION_X[1] * fw)], x0, y0


def find_menu_words(region: np.ndarray) -> dict[str, ocr.Line]:
    """Palavras do menu lidas no recorte (a primeira linha em que cada uma aparece)."""
    found: dict[str, ocr.Line] = {}
    for line in ocr.read_lines(region, min_height=OCR_UPSCALE * region.shape[0]):
        for word in re.findall(r"[a-z]+", line.text.lower()):
            if word in MENU_WORDS:
                found.setdefault(word, line)
    return found


def looks_like_menu(found: dict[str, ocr.Line]) -> bool:
    if len(found) < MIN_WORDS:
        return False
    ys = [found[w].y for w in MENU_ORDER if w in found]
    return all(a <= b for a, b in zip(ys, ys[1:]))


def is_main_menu(frame: np.ndarray | None) -> bool:
    if frame is None:
        return False
    region, _, _ = menu_region(frame)
    if region.size == 0:
        return False
    return looks_like_menu(find_menu_words(region))
