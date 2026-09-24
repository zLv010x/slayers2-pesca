import cv2
import pytest

import menu

GAME_SHOTS = [
    "idle_com_vara.webp", "idle_sem_vara.webp", "grama_com_vara.webp", "menu_inventario_fishing.webp",
    "menu_1920x991_fishing.webp", "minigame_55.webp", "prompt_golden_fish.webp",
]


def test_menu_principal_do_jogo_e_reconhecido(shot):
    # 24/09 02:28: o servidor reiniciou e o jogo voltou para o menu (PLAY / CUSTOMIZE / HUB / SLOTS)
    assert menu.is_main_menu(shot("menu_principal.webp"))


def test_menu_principal_em_janela_menor(shot):
    img = shot("menu_principal.webp")
    small = cv2.resize(img, (1280, 684), interpolation=cv2.INTER_AREA)
    assert menu.is_main_menu(small)


@pytest.mark.parametrize("name", GAME_SHOTS)
def test_jogo_normal_nao_e_menu(shot, name):
    assert not menu.is_main_menu(shot(name))


def test_uma_palavra_so_nao_basta(monkeypatch, shot):
    """Alguém da party chamado "Hub" não pode parar a pesca."""
    from ocr import Line
    monkeypatch.setattr(menu.ocr, "read_lines", lambda img, min_height=0: [Line("Hub", 0, 0, 10, 10)])
    assert not menu.is_main_menu(shot("idle_com_vara.webp"))


def test_imagem_vazia_nao_quebra():
    assert not menu.is_main_menu(None)


def _fake_lines(monkeypatch, *words_y):
    from ocr import Line
    monkeypatch.setattr(menu.ocr, "read_lines",
                        lambda img, min_height=0: [Line(w, 0, y, 40, 10) for w, y in words_y])


def test_duas_palavras_nao_bastam(monkeypatch, shot):
    """Revisão de 24/09: o PLAY fica na área da party; amigos chamados "Play" e "Hub"
    não podem virar menu (o relog clicaria na party)."""
    _fake_lines(monkeypatch, ("Play", 0), ("Hub", 40))
    assert not menu.is_main_menu(shot("idle_com_vara.webp"))


def test_tres_palavras_fora_de_ordem_nao_e_menu(monkeypatch, shot):
    _fake_lines(monkeypatch, ("Hub", 0), ("Play", 40), ("Slots", 80))
    assert not menu.is_main_menu(shot("idle_com_vara.webp"))


def test_tres_palavras_na_ordem_do_menu(monkeypatch, shot):
    _fake_lines(monkeypatch, ("Play", 0), ("Customize", 40), ("Slots", 120))
    assert menu.is_main_menu(shot("idle_com_vara.webp"))
