"""Tela do menu principal do jogo (PLAY / CUSTOMIZE / HUB / SLOTS).

Aparece quando o servidor reinicia ou a pessoa cai do jogo (24/09 02:28): sem
personagem, sem vara e sem bússola. Pescar fica impossível até alguém entrar de
novo e voltar ao ponto de pesca, então a macro para e avisa em vez de ficar
tentando (ou pausada esperando a câmera) a noite toda.

O menu fica na mesma área do painel da party: exigir 2 das 4 palavras evita
confundir com alguém do grupo chamado "Hub".
"""
from __future__ import annotations

import re

import numpy as np

import ocr

MENU_WORDS = {"play", "customize", "hub", "slots"}
MIN_WORDS = 2
REGION_X = (0.0, 0.16)
REGION_Y = (0.38, 0.62)
# O texto do menu é claro sobre fundo desfocado: o OCR lê melhor sem binarizar, ampliado.
OCR_UPSCALE = 2


def is_main_menu(frame: np.ndarray | None) -> bool:
    if frame is None:
        return False
    fh, fw = frame.shape[:2]
    region = frame[int(REGION_Y[0] * fh):int(REGION_Y[1] * fh), int(REGION_X[0] * fw):int(REGION_X[1] * fw)]
    if region.size == 0:
        return False
    words: set[str] = set()
    for line in ocr.read_lines(region, min_height=OCR_UPSCALE * region.shape[0]):
        words |= set(re.findall(r"[a-z]+", line.text.lower()))
    return len(words & MENU_WORDS) >= MIN_WORDS
