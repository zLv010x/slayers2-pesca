import pytest

from hotbar import check_rod


@pytest.mark.parametrize("name, expected", [
    ("idle_sem_vara.webp", False),
    ("idle_com_vara.webp", True),
    ("prompt_golden_fish.webp", True),
    ("popup_golden_fish.webp", True),
])
def test_detecta_se_a_vara_esta_equipada(shot, name, expected):
    assert check_rod(shot(name)).equipped is expected


def test_minigame_esconde_a_hotbar(shot):
    # Durante o minigame a hotbar some; a checagem não deve inventar vara.
    assert check_rod(shot("minigame_55.webp")).equipped is False
