import math
import random

import pytest

from minigame import BarController, BarReading, read_bar

SCAN = dict(x=0.731640625, y=0.2923611111111111, w=0.03828125, h=0.3763888888888889)


def _bar_crop(img, title_bar=18):
    img = img[title_bar:]
    h, w = img.shape[:2]
    x, y = int(SCAN["x"] * w), int(SCAN["y"] * h)
    cw, ch = int(SCAN["w"] * w), int(SCAN["h"] * h)
    pad = int(cw * 0.6)
    return img[max(0, y - int(ch * 0.05)):y + int(ch * 1.05), max(0, x - pad):x + cw + pad]


def test_le_quadrado_e_zona_verde(shot):
    r = read_bar(_bar_crop(shot("minigame_55.webp")))
    assert r is not None and r.has_zone
    assert r.zone_top < r.zone_bot
    assert r.ball_y > r.zone_mid        # no print o quadrado está abaixo do meio da zona


@pytest.mark.parametrize("name, title_bar", [
    ("idle_com_vara.webp", 18), ("prompt_golden_fish.webp", 18),
    ("popup_golden_fish.webp", 18), ("grama_com_vara.webp", 0), ("popup_coral.webp", 0),
])
def test_sem_minigame_nao_le_nada(shot, name, title_bar):
    assert read_bar(_bar_crop(shot(name), title_bar)) is None


def test_segura_abaixo_da_zona_e_solta_acima():
    c = BarController()
    assert c.update(BarReading(300, 24, 100, 140), 0.0) is True     # abaixo: sobe
    c.reset()
    assert c.update(BarReading(50, 24, 100, 140), 0.0) is False     # acima: desce


def test_sem_zona_por_muito_tempo_solta():
    c = BarController(zone_memory_s=1.0)
    c.update(BarReading(300, 24, 100, 140), 0.0)
    assert c.update(BarReading(300, 24, None, None), 2.0) is False


def _simulate(seed, fps=30.0, latency=1, real_accel=900.0, secs=20.0):
    """Minigame de mentira: segurar acelera para cima, soltar para baixo; a zona passeia."""
    rnd = random.Random(seed)
    y, v, hold, dt = 380.0, 0.0, False, 1 / fps
    ctrl, seen, inside, total, t = BarController(), [], 0, 0, 0.0
    phase = rnd.random() * 6
    while t < secs:
        mid = 200 + 130 * math.sin(t * 0.9 + phase) + 30 * math.sin(t * 2.3)
        seen.append(BarReading(y, 24, int(mid - 20), int(mid + 20)))
        if len(seen) > latency:
            hold = ctrl.update(seen[-1 - latency], t)
        v += (-real_accel if hold else real_accel) * dt
        y = min(400.0, max(0.0, y + v * dt))
        if y in (0.0, 400.0):
            v = 0.0
        if t > 1.0:
            total += 1
            inside += abs(y - mid) <= 20
        t += dt
    return inside / total


@pytest.mark.parametrize("fps, latency, accel", [(30, 1, 900), (30, 2, 900), (20, 1, 900), (30, 1, 600), (30, 1, 1300)])
def test_simulacao_mantem_o_quadrado_na_zona(fps, latency, accel):
    media = sum(_simulate(s, fps, latency, accel) for s in range(4)) / 4
    assert media >= 0.75
