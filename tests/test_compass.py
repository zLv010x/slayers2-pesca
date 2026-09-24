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


def test_janela_do_roblox_mudou_de_tamanho(shot):
    import cv2
    frame = _game(shot("idle_com_vara.webp"))
    lock = CompassLock()
    lock.capture(frame)
    for scale in (0.6, 0.8, 1.3):
        resized = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        drift = lock.drift_px(resized)
        assert drift is not None and abs(drift) <= 3, (scale, drift)


def test_janela_menor_e_camera_girada(shot):
    import cv2
    lock = CompassLock()
    lock.capture(_game(shot("idle_com_vara.webp")))
    girada = _game(shot("prompt_golden_fish.webp"))          # câmera ~20 px para o lado
    small = cv2.resize(girada, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
    drift = lock.drift_px(small)
    assert drift is not None and drift <= -10


def test_salva_e_carrega_com_o_tamanho(tmp_path, shot):
    import cv2
    frame = _game(shot("idle_com_vara.webp"))
    lock = CompassLock()
    lock.capture(frame)
    lock.save(tmp_path / "b.npz")
    back = CompassLock()
    assert back.load(tmp_path / "b.npz")
    small = cv2.resize(frame, None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA)
    assert abs(back.drift_px(small)) <= 3
