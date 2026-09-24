import numpy as np
import pytest

import ocr
from inventory import find_line, find_single_tile, has_bait_badge, read_count

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
    box = find_single_tile(_only_tile(menu, (0, 7)), search)
    assert box is not None
    assert abs(box.x - GRID_X) <= 6 and abs(box.y - GRID_Y) <= 6
    assert abs(box.w - TILE) <= 8


def test_busca_sem_resultado_nao_tem_quadrado(menu):
    search = find_line(ocr.read_lines(menu), r"item name here")
    assert find_single_tile(_only_tile(menu, None), search) is None


def test_acha_o_botao_equip_bait(menu):
    import loot
    half = menu.shape[0] // 2
    lines = ocr.read_lines(loot._white_text(menu[half:]))
    assert find_line(lines, r"equip\s*bait") is not None
