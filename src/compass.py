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
        self._strip_size: tuple[int, int] | None = None   # tamanho da faixa na marcação

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
        self._strip_size = strip.shape[:2]

    def save(self, path) -> None:
        if self._template is not None:
            np.savez(path, template=self._template, home_x=self._home_x,
                     strip_size=np.array(self._strip_size or (0, 0)))

    def load(self, path) -> bool:
        try:
            data = np.load(path)
            self._template = data["template"]
            self._home_x = int(data["home_x"])
            size = tuple(int(v) for v in data["strip_size"]) if "strip_size" in data else (0, 0)
            self._strip_size = size if size[0] > 0 else None
            return True
        except (OSError, KeyError, ValueError):
            return False

    def drift_px(self, frame: np.ndarray) -> int | None:
        """Quantos pixels a bússola andou desde a marcação (None = não achou).

        A bússola fica sempre no centro da tela e, no Roblox, tem tamanho FIXO em pixels
        (medido em 24/09: N-E = 99 px com a janela em 1280x953 e em 2560x1369). Se a janela
        mudou de tamanho, procura a referência no tamanho original e, por garantia, também
        redimensionada pela largura/altura (outra interface poderia escalar); fica a melhor.
        A posição é medida a partir do centro e volta na escala da marcação.
        """
        if self._template is None:
            return None
        strip = _strip(frame)
        best = None
        for scale in self._scales(strip.shape[:2]):
            template = self._scaled_template(scale, strip.shape)
            if template is None:
                continue
            _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED))
            if best is None or score > best[0]:
                best = (score, loc[0], template.shape[1], scale)
        if best is None or best[0] < MIN_MATCH:
            return None
        _, x, tw, scale = best
        return int(round((x - self._expected_left(strip.shape[1], tw, scale)) / scale))

    def _scales(self, strip_size: tuple[int, int]) -> list[float]:
        if not self._strip_size or strip_size == self._strip_size:
            return [1.0]
        ry = strip_size[0] / self._strip_size[0]
        rx = strip_size[1] / self._strip_size[1]
        return list(dict.fromkeys(round(s, 3) for s in (1.0, rx, ry)))

    def _scaled_template(self, scale: float, strip_shape: tuple[int, ...]) -> np.ndarray | None:
        template = self._template
        if scale != 1.0:
            th, tw = template.shape
            template = cv2.resize(template, (max(1, round(tw * scale)), max(1, round(th * scale))),
                                  interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        template = template[:strip_shape[0]]  # faixa mais baixa: as letras ficam no alto dela
        if template.shape[1] > strip_shape[1]:
            return None
        return template

    def _expected_left(self, strip_w: int, tw: int, scale: float) -> float:
        """Onde a referência fica sem giro: mesma distância do centro que na marcação."""
        cal_w = self._strip_size[1] if self._strip_size else strip_w
        cal_tw = self._template.shape[1]
        offset = self._home_x + cal_tw / 2 - cal_w / 2
        return strip_w / 2 + offset * scale - tw / 2
