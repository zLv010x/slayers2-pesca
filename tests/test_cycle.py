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


class FakeMenu:
    """Menu do jogo de mentira: inventário definido pelo teste."""

    def __init__(self, inv, fail=False):
        self.inv, self.fail = inv, fail      # inv: nome -> (quantidade|None, equipada)
        self.equipped_calls, self.closed = [], False

    def open(self):
        if self.fail:
            raise cycle.bait_menu.MenuError("menu não abriu")

    def inspect(self, name):
        if name not in self.inv:
            return cycle.bait_menu.BaitInfo(False, 0, False)
        count, eq = self.inv[name]
        return cycle.bait_menu.BaitInfo(True, count, eq)

    def equip(self, name):
        self.equipped_calls.append(name)
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def bait_env(monkeypatch):
    from baits import BaitState

    def make(inv, fail=False):
        menu = FakeMenu(inv, fail)
        monkeypatch.setattr(cycle.bait_menu, "BaitMenu", lambda fisher: menu)
        monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
        f = FakeFisher([])
        f.baits = BaitState()
        f.notifier = FakeNotifier()
        f.cfg["discord"]["notify_problems"] = True
        f._safe_shot = lambda: None
        return f, menu
    return make


def test_rare_acabou_troca_para_lendaria_e_avisa(bait_env):
    f, menu = bait_env({"Drowned Lure": (None, False), "Worm": (13, False)})  # Fish Head sumiu = 0
    f.check_baits()
    assert menu.equipped_calls == ["Drowned Lure"]
    assert f.baits.equipped == "Drowned Lure"
    assert any("Drowned Lure" in text and ping for text, ping in f.notifier.sent)
    assert menu.closed


def test_com_rare_nao_mexe_em_nada(bait_env):
    f, menu = bait_env({"Fish Head": (662, True), "Drowned Lure": (None, False)})
    f.check_baits()
    assert menu.equipped_calls == []
    assert f.baits.summary(["Drowned Lure"]).startswith("Isca: Fish Head · 662")
    assert f.notifier.sent == []


def test_amigo_sem_lendaria_vai_para_a_comum(bait_env):
    f, menu = bait_env({"Worm": (13, False)})
    f.check_baits()
    assert menu.equipped_calls == ["Worm"]


def test_sem_nenhuma_isca_avisa_uma_vez_e_continua(bait_env):
    f, menu = bait_env({})
    f.check_baits()
    f.check_baits()
    assert menu.equipped_calls == []
    assert len(f.notifier.sent) == 1 and "sem isca" in f.notifier.sent[0][0]


def test_comprou_rare_de_novo_volta_para_ela(bait_env):
    f, menu = bait_env({"Fish Head": (200, False), "Drowned Lure": (None, True)})
    f.check_baits()
    assert menu.equipped_calls == ["Fish Head"]


def test_menu_com_erro_nao_derruba_a_pesca(bait_env):
    f, menu = bait_env({}, fail=True)
    f.check_baits()
    assert menu.closed and f._bait_retry_at > f.cycles


@pytest.fixture
def game_env(monkeypatch):
    """Coleta imitando a regra do jogo: o item só vem com T apertado sem parar por GAME_HOLD
    segundos com o aviso visível; se o aviso some, o progresso zera e só volta apertando de novo."""
    from loot import Loot
    GAME_HOLD = 2.3
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    st = {"press_at": None, "broken": False, "got": False, "presses": 0}
    env = {"visible": lambda t: True, "detected": lambda t, holding: True, "st": st}

    def press(k):
        st["presses"] += 1
        st["press_at"], st["broken"] = clock.now, not env["visible"](clock.now)

    def release(k):
        st["press_at"] = None

    def read_popups(img):
        t = clock.now
        if st["press_at"] is not None:
            if not env["visible"](t):
                st["broken"] = True
            elif not st["broken"] and t - st["press_at"] >= GAME_HOLD:
                st["got"] = True
        return [Loot("Clown Fish", 1, "rare", (0, 0, 1, 1))] if st["got"] else []

    monkeypatch.setattr(cycle.screen, "press_key", press)
    monkeypatch.setattr(cycle.screen, "release_key", release)
    monkeypatch.setattr(cycle.loot_mod, "read_popups", read_popups)
    monkeypatch.setattr(cycle.prompt_mod, "find_collect_prompt",
                        lambda img: object() if env["detected"](clock.now, st["press_at"] is not None) else None)
    f = FakeFisher([])
    f.frame = lambda: (None, None)
    return f, env


def test_detector_falha_com_t_apertado_mas_item_vem(game_env):
    # bug real: com a câmera longe, o aviso vira um losango pequeno que o detector não acha
    # enquanto o T está apertado; o aviso continua na tela e o jogo precisa do T sem parar
    f, env = game_env
    env["detected"] = lambda t, holding: not holding
    fresh, _ = f._hold_t([], 12.0, "da vara")
    assert [i.name for i in fresh] == ["Clown Fish"]


def test_item_balanca_de_verdade_e_ainda_assim_vem(game_env):
    f, env = game_env
    env["visible"] = lambda t: not (1.0 <= t < 1.6)   # o aviso some de verdade por 0,6 s
    env["detected"] = lambda t, holding: env["visible"](t)
    fresh, _ = f._hold_t([], 12.0, "da vara")
    assert fresh and env["st"]["presses"] >= 2       # precisou apertar de novo depois que voltou
