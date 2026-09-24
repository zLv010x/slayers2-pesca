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


def _narrow(img, w, h):
    """Simula uma janela mais estreita do Roblox: a altura acompanha o FOV vertical
    (redimensiona por ela) e a largura é cortada, como uma janela menos larga mostraria."""
    scale = h / img.shape[0]
    new_w = max(w, round(img.shape[1] * scale))
    resized = cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
    x0 = (new_w - w) // 2
    return resized[:, x0:x0 + w]


@pytest.mark.parametrize("size", [(1137, 981), (1002, 981)])
@pytest.mark.parametrize("name", [
    "video_aviso_circulo.webp",
    "video_aviso_losango.webp",
    "prompt_golden_fish.webp",
])
def test_acha_o_aviso_em_janela_estreita(shot, name, size):
    assert find_collect_prompt(_narrow(shot(name), *size)) is not None


@pytest.mark.parametrize("size", [(1137, 981), (1002, 981)])
@pytest.mark.parametrize("name", ["video_brilho_coleta.webp", "video_depois_coleta.webp"])
def test_sem_aviso_em_janela_estreita(shot, name, size):
    assert find_collect_prompt(_narrow(shot(name), *size)) is None


def test_sem_aviso_em_janela_estreita_real(shot):
    # print real do jogo em janela de 1002x981 (log do amigo): depois de coletar, sem aviso
    assert find_collect_prompt(shot("popup_janela_1002.webp")) is None
