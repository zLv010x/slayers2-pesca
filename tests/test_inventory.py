import numpy as np
import pytest

import ocr
from inventory import find_line, find_tiles, has_bait_badge, is_active_tab, read_count

TITLE_BAR = 18
TILE, STEP, GRID_X, GRID_Y = 70, 78, 737, 99  # posições no print do menu (sem a barra de título)


@pytest.fixture
def menu(shot):
    return shot("menu_inventario_fishing.webp")[TITLE_BAR:]


def tile(menu, row, col):
    x, y = GRID_X + STEP * col, GRID_Y + 77 * row
    return menu[y:y + TILE, x:x + TILE]


def test_le_quantidade_das_iscas(menu):
    assert read_count(tile(menu, 0, 7)) == 662   # Fish Head (rare): chifre encosta na pílula
    assert read_count(tile(menu, 0, 5)) == 13    # Worm (common)


def test_isca_lendaria_nao_tem_quantidade(menu):
    assert read_count(tile(menu, 1, 2)) is None  # Drowned Lure: não gasta, não tem pílula


def test_selo_bait_da_isca_equipada(menu):
    assert has_bait_badge(tile(menu, 0, 7))
    assert not has_bait_badge(tile(menu, 0, 5))


def test_acha_os_textos_do_menu(menu):
    lines = ocr.read_lines(menu)
    assert find_line(lines, r"item name here") is not None
    assert find_line(lines, r"^fishing \(") is not None
    assert find_line(lines, r"inventory") is not None


def _only_tile(menu, keep):
    """Simula a tela depois de buscar um nome: só um quadrado na grade."""
    fake = menu.copy()
    fake[GRID_Y - 5:GRID_Y + 170, GRID_X - 5:GRID_X + 790] = 18
    if keep is not None:
        fake[GRID_Y:GRID_Y + TILE, GRID_X:GRID_X + TILE] = tile(menu, *keep)
    return fake


def test_acha_o_quadrado_que_sobrou_na_busca(menu):
    search = find_line(ocr.read_lines(menu), r"item name here")
    tiles = find_tiles(_only_tile(menu, (0, 7)), search)
    assert len(tiles) == 1
    box = tiles[0]
    assert abs(box.x - GRID_X) <= 6 and abs(box.y - GRID_Y) <= 6
    assert abs(box.w - TILE) <= 8


def test_busca_sem_resultado_nao_tem_quadrado(menu):
    search = find_line(ocr.read_lines(menu), r"item name here")
    assert find_tiles(_only_tile(menu, None), search) == []


def test_acha_o_botao_equip_bait(menu):
    import loot
    half = menu.shape[0] // 2
    lines = ocr.read_lines(loot._white_text(menu[half:]))
    assert find_line(lines, r"equip\s*bait") is not None


def test_aba_fishing_selecionada_e_as_outras_nao(shot):
    for name in ("menu_inventario_fishing.webp", "menu_busca_sem_enter.webp"):
        img = shot(name)
        lines = ocr.read_lines(img)
        assert is_active_tab(img, find_line(lines, r"^fishing\s*\("))
        assert not is_active_tab(img, find_line(lines, r"^face\s*\("))


def test_busca_sem_enter_mostra_varios_itens(shot):
    # print real: "Fish Head" digitado, mas sem Enter a grade continuou com tudo
    img = shot("menu_busca_sem_enter.webp")
    search = find_line(ocr.read_lines(img), r"fish head")
    assert len(find_tiles(img, search)) > 1


def test_menu_aberto_e_reconhecido_mesmo_com_texto_na_busca(shot):
    from bait_menu import BaitMenu
    img = shot("menu_aberto_333.webp")   # busca com "333" digitado por engano
    assert BaitMenu(None)._menu_open(ocr.read_lines(img), img)
    jogo = shot("popup_coral.webp")
    assert not BaitMenu(None)._menu_open(ocr.read_lines(jogo), jogo)


def test_digita_na_busca_e_aperta_enter(monkeypatch):
    import bait_menu
    from window import Rect
    keys = []
    monkeypatch.setattr(bait_menu.screen, "click_at", lambda x, y: keys.append(("click", x, y)))
    monkeypatch.setattr(bait_menu.screen, "tap_key", lambda k, hold_sec=0.08: keys.append(k))
    monkeypatch.setattr(bait_menu.screen, "type_text", lambda t: keys.append(("texto", t)))
    fisher = type("F", (), {"frame": lambda self: (Rect(0, 0, 100, 100), None), "sleep": lambda self, s: None})()
    menu = bait_menu.BaitMenu(fisher)
    menu.search_box = ocr.Line("Item name here!", 10, 10, 50, 10)
    menu._type_search("Fish Head")
    assert keys[0][0] == "click"
    assert ("texto", "Fish Head") in keys
    assert keys[-1] == "enter"       # o jogo só filtra depois do Enter
