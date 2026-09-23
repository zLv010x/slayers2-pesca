import copy
import threading

import pytest

import config
import cycle
from hotbar import RodCheck


class FakeFisher(cycle.Fisher):
    """Fisher sem tela de verdade: a hotbar responde a partir de uma lista."""

    def __init__(self, equipped_seq):
        cb = cycle.Callbacks(status=lambda m: None, loot=lambda items, snap: None)
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["timings"]["rod_equip_wait_sec"] = 0
        cfg["discord"]["notify_problems"] = False
        super().__init__(cfg, cb, session=None, notifier=None, compass=None)
        self._seq = list(equipped_seq)
        self._stop = threading.Event()

    def frame(self):
        return None, self._seq.pop(0)


@pytest.fixture
def presses(monkeypatch):
    keys = []
    monkeypatch.setattr(cycle.screen, "tap_key", lambda k, *a, **kw: keys.append(k))
    monkeypatch.setattr(cycle.hotbar, "check_rod", lambda equipped: RodCheck(equipped, 0, 0, 0))
    return keys


def test_vara_ja_na_mao_nao_aperta_nada(presses):
    FakeFisher([True]).ensure_rod()
    assert presses == []


def test_vara_fora_aperta_uma_vez_e_confere(presses):
    FakeFisher([False, True]).ensure_rod()
    assert presses == ["3"]


def test_desiste_e_para_se_nunca_equipar(presses):
    f = FakeFisher([False] * 10)
    with pytest.raises(cycle.StopRun):
        f.ensure_rod()
    # uma tecla por tentativa, sempre conferindo a hotbar entre elas
    assert presses == ["3"] * config.DEFAULTS["limits"]["rod_retries"]
