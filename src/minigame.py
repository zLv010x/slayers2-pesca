"""Minigame da pesca: ler a barra e decidir segurar/soltar o clique.

A barra é vertical. Dentro dela há uma zona verde (que se mexe) e um quadrado
branco. Segurando o clique o quadrado sobe; soltando ele desce. O objetivo é
manter o quadrado dentro da zona verde.

Leitura: quadrado = pixels claros e sem cor; zona = linhas com verde forte.
Controle: calcula onde o quadrado pararia se a força fosse invertida agora e
segura se ele pararia abaixo do meio da zona (solta se pararia acima).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Quadrado branco: claro e quase sem cor.
BALL_MIN_BRIGHT = 190
BALL_MAX_SAT = 50
BALL_MIN_SIDE_FRAC = 0.06      # lado mínimo em fração da largura do recorte da barra
BALL_ASPECT = (0.4, 2.5)       # a parte de cima pode ficar esverdeada: aceita meio quadrado
# Zona verde: verde bem mais forte que vermelho e azul.
ZONE_MIN_G = 110
ZONE_MIN_MARGIN = 35
ZONE_MIN_PIXELS_PER_ROW = 2
ZONE_MAX_GAP_ROWS = 3


@dataclass(frozen=True)
class BarReading:
    ball_y: float              # centro do quadrado (px, dentro do recorte)
    ball_h: int
    zone_top: int | None
    zone_bot: int | None

    @property
    def zone_mid(self) -> float | None:
        if self.zone_top is None:
            return None
        return (self.zone_top + self.zone_bot) / 2.0

    @property
    def has_zone(self) -> bool:
        return self.zone_top is not None


def _green_rows(img: np.ndarray) -> tuple[int, int] | None:
    """Faixa (topo, fundo) de linhas com verde forte; pega o maior trecho contínuo."""
    b, g, r = (img[..., i].astype(np.int16) for i in range(3))
    green = (g >= ZONE_MIN_G) & (g - r >= ZONE_MIN_MARGIN) & (g - b >= ZONE_MIN_MARGIN)
    rows = np.nonzero(green.sum(axis=1) >= ZONE_MIN_PIXELS_PER_ROW)[0]
    if rows.size == 0:
        return None
    best, start, prev = None, rows[0], rows[0]
    for y in list(rows[1:]) + [None]:
        if y is not None and y - prev <= ZONE_MAX_GAP_ROWS + 1:
            prev = y
            continue
        if best is None or prev - start > best[1] - best[0]:
            best = (int(start), int(prev))
        if y is not None:
            start = prev = y
    return best


def _ball(img: np.ndarray) -> tuple[float, int] | None:
    lo = img.min(axis=2)
    sat = img.max(axis=2).astype(np.int16) - lo
    white = ((lo >= BALL_MIN_BRIGHT) & (sat <= BALL_MAX_SAT)).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(white)
    min_side = max(3, int(BALL_MIN_SIDE_FRAC * img.shape[1]))
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < min_side or h < min_side // 2:
            continue
        if not BALL_ASPECT[0] <= w / h <= BALL_ASPECT[1]:
            continue
        if best is None or area > best[2]:
            best = (float(y + h / 2.0), int(w), area)
    return (best[0], best[1]) if best else None


def read_bar(img: np.ndarray) -> BarReading | None:
    """Lê o recorte da barra. None = não tem quadrado branco (sem minigame)."""
    ball = _ball(img)
    if ball is None:
        return None
    zone = _green_rows(img)
    return BarReading(ball[0], ball[1], zone[0] if zone else None, zone[1] if zone else None)


class BarController:
    """Decide segurar/soltar pelo "ponto de parada" do quadrado.

    Segurando, o quadrado acelera para cima; soltando, para baixo (mesma força).
    A cada leitura: avança o estado pelo atraso (lead_s) e calcula onde o quadrado
    pararia se a força fosse invertida agora. Se ele pararia abaixo do meio da
    zona, segura; se pararia acima, solta. É o controle "liga/desliga" de tempo
    mínimo para um objeto com aceleração constante.
    """

    def __init__(self, lead_s: float = 0.02, deadband: float = 0.05, accel: float = 37.5,
                 zone_memory_s: float = 1.0, smooth: float = 0.5) -> None:
        self.lead_s = lead_s                # atraso extra (além do tempo entre leituras)
        self.deadband = deadband            # fração da meia-altura da zona
        self.accel = accel                  # aceleração do quadrado, em alturas-de-quadrado/s²
        self.zone_memory_s = zone_memory_s
        self.smooth = smooth
        self.reset()

    def configure(self, cfg: dict) -> None:
        self.lead_s = float(cfg.get("lead_s", self.lead_s))
        self.deadband = float(cfg.get("deadband", self.deadband))
        self.accel = max(1.0, float(cfg.get("accel", self.accel)))
        self.zone_memory_s = float(cfg.get("zone_memory_s", self.zone_memory_s))

    def reset(self) -> None:
        self.hold = False
        self._y: float | None = None
        self._t = 0.0
        self.v = 0.0
        self._dt = 0.0                                  # tempo médio entre leituras
        self._zone: tuple[float, float] | None = None   # (meio, meia-altura)
        self._zone_t = 0.0

    def update(self, reading: BarReading, now: float) -> bool:
        if self._y is not None and now > self._t:
            dt = now - self._t
            raw_v = (reading.ball_y - self._y) / dt
            self.v = self.smooth * raw_v + (1 - self.smooth) * self.v
            self._dt = dt if self._dt <= 0 else 0.8 * self._dt + 0.2 * dt
        self._y, self._t = reading.ball_y, now
        if reading.has_zone:
            half = max(1.0, (reading.zone_bot - reading.zone_top) / 2.0)
            self._zone, self._zone_t = (reading.zone_mid, half), now
        if self._zone is None or now - self._zone_t > self.zone_memory_s:
            self.hold = False
            return self.hold
        mid, half = self._zone
        # y cresce para baixo; segurando a aceleração é para cima (negativa)
        a_max = self.accel * max(1, reading.ball_h)
        a_now = -a_max if self.hold else a_max
        # PC mais lento = mais tempo entre ver e reagir: a previsão cresce junto
        lead = self.lead_s + self._dt
        y = reading.ball_y + self.v * lead + 0.5 * a_now * lead * lead
        v = self.v + a_now * lead
        # onde pararia freando com a força máxima: positivo = abaixo do meio → segurar
        stop = (y - mid) + v * abs(v) / (2 * a_max)
        band = self.deadband * half
        if stop > band:
            self.hold = True
        elif stop < -band:
            self.hold = False
        return self.hold
