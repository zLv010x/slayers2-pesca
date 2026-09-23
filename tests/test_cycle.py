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


def test_vara_que_nao_equipa_vira_recuperacao_nao_parada(presses):
    f = FakeFisher([False] * 10)
    with pytest.raises(cycle.Recoverable):
        f.ensure_rod()
    # uma tecla por tentativa, sempre conferindo a hotbar entre elas
    assert presses == ["3"] * config.DEFAULTS["limits"]["rod_retries"]


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_text(self, text, ping=False):
        self.sent.append((text, ping))


def test_recupera_varias_vezes_e_so_desiste_no_limite(monkeypatch):
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: None)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.cfg["timings"]["recovery_wait_sec"] = 0
    f.cfg["discord"]["notify_problems"] = True
    limit = f.cfg["limits"]["max_recoveries"]
    for _ in range(limit):
        f._recover("teste", None)  # não pode parar
    with pytest.raises(cycle.StopRun):
        f._recover("teste", None)
    # só marca você no primeiro aviso de uma sequência, para não lotar o Discord
    assert [ping for _, ping in f.notifier.sent[:2]] == [True, False]
