import pytest

from hotbar import check_rod


@pytest.mark.parametrize("name, expected", [
    ("idle_sem_vara.webp", False),
    ("idle_com_vara.webp", True),
    ("prompt_golden_fish.webp", True),
    ("popup_golden_fish.webp", True),
    ("grama_com_vara.webp", True),    # print real em 2560 px, grama verde atrás da hotbar
    ("grama_sem_vara.webp", False),   # o disco semi-transparente fica verde: não pode enganar
])
def test_detecta_se_a_vara_esta_equipada(shot, name, expected):
    assert check_rod(shot(name)).equipped is expected


def test_minigame_esconde_a_hotbar(shot):
    # Durante o minigame a hotbar some; a checagem não deve inventar vara.
    assert check_rod(shot("minigame_55.webp")).equipped is False


@pytest.mark.parametrize("name, expected", [
    ("grama_com_vara.webp", True),
    ("idle_com_vara.webp", True),
    ("idle_sem_vara.webp", False),
])
def test_fundo_colorido_atras_da_hotbar_nao_engana(shot, name, expected):
    import cv2
    import numpy as np
    img = shot(name).copy()
    h = img.shape[0]
    band = img[int(h * 0.86):].astype(np.float32)
    green = np.zeros_like(band)
    green[..., 1] = 255
    # o disco é semi-transparente: grama verde por trás deixa tudo esverdeado
    img[int(h * 0.86):] = cv2.addWeighted(band, 0.7, green, 0.3, 0).astype(np.uint8)
    assert check_rod(img).equipped is expected
