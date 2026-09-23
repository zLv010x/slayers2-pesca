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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def perf_counter(self):
        return self.now

    def sleep(self, sec):
        self.now += max(sec, 0.01)


@pytest.fixture
def collect_env(monkeypatch):
    """Coleta com relógio falso: o teste decide quando o aviso de coleta e o drop aparecem."""
    from loot import Loot
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    keys = []
    monkeypatch.setattr(cycle.screen, "press_key", lambda k: keys.append(("press", k, clock.now)))
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: keys.append(("release", k, clock.now)))
    env = {"prompt": lambda t: True, "drop_at": None, "keys": keys, "clock": clock}
    monkeypatch.setattr(cycle.prompt_mod, "find_collect_prompt",
                        lambda img: object() if env["prompt"](clock.now) else None)
    fish = Loot("Coral", 1, "common", (0, 0, 1, 1))
    monkeypatch.setattr(cycle.loot_mod, "read_popups",
                        lambda img: [fish] if env["drop_at"] is not None and clock.now >= env["drop_at"] else [])
    f = FakeFisher([])
    f.frame = lambda: (None, None)
    return f, env


def _presses(env):
    return [k for k in env["keys"] if k[0] == "press"]


def test_item_balancando_recomeca_o_t_quando_o_aviso_volta(collect_env):
    f, env = collect_env
    # aviso some entre 1,0 s e 1,6 s (item balançou); o jogo zera o T
    env["prompt"] = lambda t: not (1.0 <= t < 1.6)
    env["drop_at"] = 1.6 + f.t("collect_hold_sec")  # só pega segurando 3 s seguidos DEPOIS de voltar
    fresh, _ = f._hold_t([], 12.0, "da vara")
    assert [i.name for i in fresh] == ["Coral"]
    assert len(_presses(env)) == 2          # apertou, soltou quando sumiu, apertou de novo
    assert env["keys"][-1][0] == "release"  # nunca termina com T preso


def test_piscada_rapida_do_aviso_nao_solta_o_t(collect_env):
    f, env = collect_env
    env["prompt"] = lambda t: not (1.0 <= t < 1.1)  # sumiu só 0,1 s (erro de detecção)
    env["drop_at"] = 3.2
    fresh, _ = f._hold_t([], 12.0, "da vara")
    assert fresh and len(_presses(env)) == 1


def test_sem_detectar_o_aviso_segura_no_escuro(collect_env):
    f, env = collect_env
    env["prompt"] = lambda t: False
    env["drop_at"] = 4.5
    fresh, _ = f._hold_t([], 12.0, "da vara")
    assert fresh and len(_presses(env)) == 1


def test_desiste_no_tempo_limite_sem_travar(collect_env):
    f, env = collect_env
    env["prompt"] = lambda t: int(t * 2) % 2 == 0  # balança sem parar: some a cada meio segundo
    fresh, _ = f._hold_t([], 5.0, "da vara")
    assert fresh == []
    assert env["clock"].now < 5.0 + f.t("popup_wait_sec") + 1
    assert env["keys"][-1][0] == "release"


def test_se_nao_vier_da_vara_guarda_a_vara_e_tenta_do_chao(presses, monkeypatch, tmp_path):
    from loot import Loot
    from session import Session
    f = FakeFisher([True] * 5)
    f.session = Session(log_dir=tmp_path)
    f.cfg["timings"]["after_minigame_sec"] = 0
    f.cfg["timings"]["after_collect_sec"] = 0
    f.cfg["discord"]["send_image"] = False
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img: [])
    monkeypatch.setattr(cycle.loot_mod, "item_snapshot", lambda img, item: None)
    f.notifier = type("N", (), {"send_loot": lambda self, r: None})()
    fish = Loot("Coral", 1, "common", (0, 0, 1, 1))
    tries = []

    def fake_hold(before, budget, where):
        tries.append(where)
        return ([fish], None) if where == "do chão" else ([], None)

    f._hold_t = fake_hold
    got = f.collect()
    assert tries == ["da vara", "do chão"]
    assert presses == ["3"]                 # guardou a vara uma vez (volta no próximo ciclo)
    assert [i.name for i in got] == ["Coral"]
    assert f.session.catches == 1 and f.session.misses == 0


def test_opcao_desligada_nao_mexe_na_vara(presses, monkeypatch, tmp_path):
    from session import Session
    f = FakeFisher([True] * 5)
    f.session = Session(log_dir=tmp_path)
    f.cfg["ground_pickup"] = False
    f.cfg["timings"]["after_minigame_sec"] = 0
    f.cfg["timings"]["after_collect_sec"] = 0
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img: [])
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    f._hold_t = lambda before, budget, where: ([], None)
    assert f.collect() == []
    assert presses == [] and f.session.misses == 1
