import cv2
import pytest

from prompt import find_collect_prompt


def test_acha_o_aviso_de_coleta(shot):
    p = find_collect_prompt(shot("prompt_golden_fish.webp"))
    assert p is not None
    assert abs(p.x - 930) <= 3 and abs(p.y - 521) <= 3


def test_acha_na_resolucao_real_2560(shot):
    img = shot("prompt_golden_fish.webp")
    big = cv2.resize(img, None, fx=1.28, fy=1.28, interpolation=cv2.INTER_CUBIC)
    assert find_collect_prompt(big) is not None


@pytest.mark.parametrize("name", [
    "popup_golden_fish.webp",   # depois de pegar: aviso de coleta já sumiu
    "idle_com_vara.webp",       # personagem branco não pode virar "T"
    "idle_sem_vara.webp",
    "minigame_55.webp",
    "popup_coral.webp",         # print real do jogo em 2560 px
])
def test_sem_aviso_de_coleta(shot, name):
    assert find_collect_prompt(shot(name)) is None


@pytest.mark.parametrize("name", [
    "video_aviso_circulo.webp",       # antes de apertar T: círculo
    "video_aviso_losango.webp",       # segurando T: vira losango com a seta de progresso
    "video_losango_na_vara_1.webp",   # losango encostado na vara branca (falhava)
    "video_losango_na_vara_2.webp",
    "video_losango_na_vara_3.webp",
])
def test_acha_o_aviso_nos_quadros_do_video(shot, name):
    assert find_collect_prompt(shot(name)) is not None


@pytest.mark.parametrize("name", ["video_brilho_coleta.webp", "video_depois_coleta.webp"])
def test_sem_aviso_depois_de_coletar_no_video(shot, name):
    assert find_collect_prompt(shot(name)) is None
