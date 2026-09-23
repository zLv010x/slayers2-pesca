"""Trava da câmera usando a bússola do topo da tela (W  315°  N  45°  E ...).

Ao marcar o ponto de lançamento guardamos um pedaço da bússola. Antes de cada
lançamento procuramos esse pedaço de novo: se ele andou para os lados, a câmera
girou e o clique cairia em outro lugar.
"""
from __future__ import annotations

import cv2
import numpy as np

# Faixa da bússola, em fração da área do jogo.
STRIP_Y = (0.0, 0.035)
STRIP_X = (0.30, 0.70)
# Pedaço guardado: o centro da faixa.
TEMPLATE_X = (0.40, 0.60)
# Realça as letras claras da bússola e ignora o céu/fundo atrás dela.
TOPHAT_KERNEL = np.ones((1, 25), np.uint8)
# Abaixo disso a correspondência não é confiável (bússola coberta, tela preta...).
MIN_MATCH = 0.6


def _strip(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    y0, y1 = int(STRIP_Y[0] * h), max(int(STRIP_Y[1] * h), 8)
    x0, x1 = int(STRIP_X[0] * w), int(STRIP_X[1] * w)
    gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return cv2.morphologyEx(cv2.GaussianBlur(gray, (3, 3), 0), cv2.MORPH_TOPHAT, TOPHAT_KERNEL)


class CompassLock:
    def __init__(self) -> None:
        self._template: np.ndarray | None = None
        self._home_x = 0

    @property
    def ready(self) -> bool:
        return self._template is not None

    def capture(self, frame: np.ndarray) -> None:
        strip = _strip(frame)
        sw = strip.shape[1]
        span = STRIP_X[1] - STRIP_X[0]
        tx0 = int((TEMPLATE_X[0] - STRIP_X[0]) / span * sw)
        tx1 = int((TEMPLATE_X[1] - STRIP_X[0]) / span * sw)
        self._template = strip[:, tx0:tx1].copy()
        self._home_x = tx0

    def save(self, path) -> None:
        if self._template is not None:
            np.savez(path, template=self._template, home_x=self._home_x)

    def load(self, path) -> bool:
        try:
            data = np.load(path)
            self._template = data["template"]
            self._home_x = int(data["home_x"])
            return True
        except (OSError, KeyError, ValueError):
            return False

    def drift_px(self, frame: np.ndarray) -> int | None:
        """Quantos pixels a bússola andou desde a marcação (None = não achou)."""
        if self._template is None:
            return None
        strip = _strip(frame)
        if strip.shape[0] < self._template.shape[0] or strip.shape[1] < self._template.shape[1]:
            return None
        res = cv2.matchTemplate(strip, self._template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score < MIN_MATCH:
            return None
        return int(loc[0] - self._home_x)
