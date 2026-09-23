import numpy as np

from compass import CompassLock

TITLE_BAR = 18  # os prints incluem a barra de título do Windows


def _game(img):
    return img[TITLE_BAR:]


def test_mesma_tela_nao_andou(shot):
    frame = _game(shot("idle_com_vara.webp"))
    lock = CompassLock()
    lock.capture(frame)
    assert lock.drift_px(frame) == 0


def test_detecta_camera_girada(shot):
    frame = _game(shot("idle_com_vara.webp"))
    lock = CompassLock()
    lock.capture(frame)
    girada = np.roll(frame, 25, axis=1)
    assert abs(lock.drift_px(girada) - 25) <= 1


def test_prints_reais_com_camera_diferente(shot):
    lock = CompassLock()
    lock.capture(_game(shot("idle_com_vara.webp")))
    # No print do prompt a câmera estava virada mais para leste (N em ~905 em vez de ~925).
    drift = lock.drift_px(_game(shot("prompt_golden_fish.webp")))
    assert drift is not None and drift <= -10
