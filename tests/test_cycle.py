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


def _as_lost(is_menu):
    """Simula a tela do jogo caído: `is_menu(img)` verdadeiro = menu principal na tela."""
    import relog
    menu_screen = relog.Screen(kind="main_menu", play_pos=(1, 1))
    return lambda img, cfg=None: menu_screen if is_menu(img) else None


@pytest.fixture(autouse=True)
def no_real_cursor(monkeypatch):
    """Nenhum teste do ciclo pode mexer no cursor de verdade."""
    moves = []
    monkeypatch.setattr(cycle.screen, "move_to",
                        lambda x, y: moves.append((x, y)) or cycle.screen.MoveResult(True, "ok", (x, y)))
    return moves


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
    monkeypatch.setattr(cycle.screen, "release_right_button", lambda: None)
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
                        lambda img, **kw: [fish] if env["drop_at"] is not None and clock.now >= env["drop_at"] else [])
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


def test_reinicia_o_t_sem_deixar_passar_muito_da_folga_com_aviso_sempre_visivel(collect_env):
    """Log real: tentativas de 4,5-4,7s de T seguro (com aviso na tela) falharam; a que
    funcionou segurou só ~2,4s. Por isso a folga (HOLD_SLACK_SEC) tem que ser curta:
    reinicia pouco depois do mínimo de 3,25s, não deixa passar de ~3,8s."""
    f, env = collect_env
    env["prompt"] = lambda t: True  # aviso sempre visível, sem cair (nunca "sumiu")
    fresh, _ = f._hold_t([], 8.0, "da vara")
    assert fresh == []
    presses = _presses(env)
    releases = [k for k in env["keys"] if k[0] == "release"]
    assert len(presses) >= 2
    first_hold = releases[0][2] - presses[0][2]
    assert 3.25 <= first_hold <= 3.8


def test_volta_a_segurar_no_escuro_depois_de_soltar_se_o_aviso_sumiu_de_vez(collect_env):
    """Bug: depois que o aviso é visto uma vez e some para sempre, o modo às cegas
    ficava travado (seen_any=True desliga o "blind") e o T nunca mais era apertado."""
    f, env = collect_env
    # aviso só aparece entre 1,5 s e 2,5 s; depois nunca mais volta (sem item)
    env["prompt"] = lambda t: 1.5 <= t < 2.5
    fresh, _ = f._hold_t([], 12.0, "da vara")
    presses = _presses(env)
    assert len(presses) >= 3
    releases = [k for k in env["keys"] if k[0] == "release"]
    # o 2º aperto vem logo depois de soltar (às cegas), não só perto do fim do orçamento
    assert presses[1][2] - releases[0][2] <= 1.1


def test_se_nao_vier_da_vara_guarda_a_vara_e_tenta_do_chao(presses, monkeypatch, tmp_path):
    from loot import Loot
    from session import Session
    f = FakeFisher([True] * 5)
    f.session = Session(log_dir=tmp_path)
    f.cfg["timings"]["after_minigame_sec"] = 0
    f.cfg["timings"]["after_collect_sec"] = 0
    f.cfg["discord"]["send_image"] = False
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img, **kw: [])
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
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img, **kw: [])
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    f._hold_t = lambda before, budget, where: ([], None)
    assert f.collect() == []
    assert presses == [] and f.session.misses == 1


def test_recoveries_nao_zera_antes_de_coletar_com_sucesso(monkeypatch):
    """Se collect() falhar toda vez, o contador de recuperações não pode voltar a 0 antes disso
    (senão a macro nunca desiste e fica presa recuperando a noite toda)."""
    f = FakeFisher([])
    f.recoveries = 3
    monkeypatch.setattr(f, "_maybe_check_baits", lambda: None)
    monkeypatch.setattr(f, "ensure_rod", lambda: None)
    monkeypatch.setattr(f, "check_camera", lambda: None)
    monkeypatch.setattr(f, "cast", lambda: None)
    monkeypatch.setattr(f, "minigame", lambda: True)

    def boom():
        raise RuntimeError("falha ao coletar")

    monkeypatch.setattr(f, "collect", boom)
    with pytest.raises(RuntimeError):
        f.one_cycle()
    assert f.recoveries == 3


def test_recoveries_zera_so_depois_do_ciclo_inteiro_dar_certo(monkeypatch):
    f = FakeFisher([])
    f.recoveries = 3
    monkeypatch.setattr(f, "_maybe_check_baits", lambda: None)
    monkeypatch.setattr(f, "ensure_rod", lambda: None)
    monkeypatch.setattr(f, "check_camera", lambda: None)
    monkeypatch.setattr(f, "cast", lambda: None)
    monkeypatch.setattr(f, "minigame", lambda: True)
    monkeypatch.setattr(f, "collect", lambda: [])
    f.one_cycle()
    assert f.recoveries == 0


def test_roblox_nao_encontrado_avisa_no_discord_depois_de_esperar(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.cfg["timings"]["recovery_wait_sec"] = 5.0
    f.cfg["discord"]["notify_problems"] = True
    calls = {"n": 0}

    def find_roblox():
        calls["n"] += 1
        if calls["n"] > 15:  # 15 * FOREGROUND_POLL_SEC (0,5s) = 7,5s virtuais > recovery_wait_sec
            f._stop.set()
        return None

    monkeypatch.setattr(cycle.window, "find_roblox", find_roblox)
    with pytest.raises(cycle.StopRun):
        f.rect()
    avisos = [t for t, _ in f.notifier.sent]
    assert any("Roblox não encontrado" in t for t in avisos)


def test_roblox_fora_da_frente_avisa_no_discord_uma_vez(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.hwnd = 1
    f.cfg["timings"]["recovery_wait_sec"] = 5.0
    f.cfg["timings"]["refocus_after_sec"] = 0  # não tenta focar sozinho neste teste
    f.cfg["discord"]["notify_problems"] = True
    monkeypatch.setattr(cycle.window, "client_rect", lambda hwnd: cycle.window.Rect(0, 0, 100, 100))
    calls = {"n": 0}

    def is_foreground(hwnd):
        calls["n"] += 1
        if calls["n"] > 15:
            f._stop.set()
        return False

    monkeypatch.setattr(cycle.window, "is_foreground", is_foreground)
    with pytest.raises(cycle.StopRun):
        f.rect()
    avisos = [t for t, _ in f.notifier.sent if "não está na frente" in t]
    assert len(avisos) == 1  # só avisa uma vez por pausa


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

    def read_popups(img, **kw):
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


def test_t_fica_apertado_pelo_menos_3_25s(game_env, monkeypatch):
    # pedido do usuário: mesmo o detector perdendo o aviso, nunca soltar T antes de 3,25 s
    f, env = game_env
    env["visible"] = lambda t: False                       # o item nunca vem: só observa o T
    env["detected"] = lambda t, holding: not holding       # detector perde o aviso com T apertado
    presses, releases = [], []
    monkeypatch.setattr(cycle.screen, "press_key", lambda k: presses.append(cycle.time.perf_counter()))
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: releases.append(cycle.time.perf_counter()))
    f._hold_t([], 8.0, "da vara")
    assert presses
    first_press = presses[0]
    first_release = min(r for r in releases if r > first_press)
    assert first_release - first_press >= cycle.MIN_T_HOLD_SEC


# ---------------------------------------------------------------- cast()

@pytest.fixture
def cast_env(monkeypatch):
    """cast() com relógio falso e rect() de mentira (sem depender do Roblox de verdade)."""
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    f = FakeFisher([])
    f.rect = lambda: cycle.window.Rect(0, 0, 100, 100)
    f.cfg["cast_point"] = {"x": 0.5, "y": 0.5}
    f.cfg["timings"]["after_cast_sec"] = 0
    f.notifier = FakeNotifier()
    f.cfg["discord"]["notify_problems"] = True
    return f, clock


def test_lancamento_com_mouse_em_uso_tenta_de_novo_sem_contar_recuperacao(cast_env, monkeypatch):
    f, clock = cast_env
    monkeypatch.setattr(cycle.screen, "on_monitor", lambda x, y: True)
    monkeypatch.setattr(cycle.screen, "click_at",
                        lambda x, y: cycle.screen.MoveResult(False, "mexendo", (x + 5, y + 5)))
    waits = []
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: waits.append(1))
    with pytest.raises(cycle.Recoverable):
        f.cast()
    # tenta CAST_BUSY_TRIES vezes, espera entre elas (uma a menos que as tentativas)
    assert len(waits) == cycle.CAST_BUSY_TRIES - 1
    assert f.recoveries == 0  # não é _recover quem trata isso: quem conta é o `run()`


def test_lancamento_com_mouse_preso_tambem_tenta_de_novo(cast_env, monkeypatch):
    f, clock = cast_env
    monkeypatch.setattr(cycle.screen, "on_monitor", lambda x, y: True)
    monkeypatch.setattr(cycle.screen, "click_at",
                        lambda x, y: cycle.screen.MoveResult(False, "preso", (x, y)))
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: None)
    with pytest.raises(cycle.Recoverable):
        f.cast()


def test_lancamento_recupera_se_o_mouse_ficar_livre_antes_do_limite(cast_env, monkeypatch):
    f, clock = cast_env
    monkeypatch.setattr(cycle.screen, "on_monitor", lambda x, y: True)
    attempts = {"n": 0}

    def fake_click(x, y):
        attempts["n"] += 1
        if attempts["n"] < 2:
            return cycle.screen.MoveResult(False, "mexendo", (x + 5, y + 5))
        return cycle.screen.MoveResult(True, "ok", (x, y))

    monkeypatch.setattr(cycle.screen, "click_at", fake_click)
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: None)
    f.cast()  # não deve levantar Recoverable
    assert attempts["n"] == 2


def test_lancamento_fora_do_monitor_pausa_ate_a_janela_voltar_sem_recuperar(cast_env, monkeypatch):
    f, clock = cast_env
    f.cfg["timings"]["recovery_wait_sec"] = 999  # não notifica durante o teste
    monitor_calls = []

    def fake_on_monitor(x, y):
        monitor_calls.append((x, y))
        return len(monitor_calls) > 2  # só "volta" na 3ª conferência

    clicks = []
    monkeypatch.setattr(cycle.screen, "on_monitor", fake_on_monitor)
    monkeypatch.setattr(cycle.screen, "click_at",
                        lambda x, y: clicks.append((x, y)) or cycle.screen.MoveResult(True, "ok", (x, y)))
    f.cast()
    assert len(monitor_calls) == 3
    assert clicks == [(50, 50)]
    assert f.recoveries == 0
    assert f.notifier.sent == []  # dentro do recovery_wait_sec: nenhum aviso ainda


def test_lancamento_fora_do_monitor_avisa_no_discord_apos_o_tempo(cast_env, monkeypatch):
    f, clock = cast_env
    f.cfg["timings"]["recovery_wait_sec"] = 0
    monitor_calls = []

    def fake_on_monitor(x, y):
        monitor_calls.append((x, y))
        return len(monitor_calls) > 1

    monkeypatch.setattr(cycle.screen, "on_monitor", fake_on_monitor)
    monkeypatch.setattr(cycle.screen, "click_at",
                        lambda x, y: cycle.screen.MoveResult(True, "ok", (x, y)))
    f.cast()
    assert any("fora do monitor" in text for text, _ in f.notifier.sent)


# ---------------------------------------------------------------- check_camera()

class FakeCompass:
    """Bússola de mentira: os desvios de cada leitura já vêm prontos."""

    def __init__(self, drifts):
        self.ready = True
        self._drifts = list(drifts)

    def drift_px(self, img):
        return self._drifts.pop(0)


def test_camera_espera_botao_direito_soltar_depois_de_voltar(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    f = FakeFisher([None, None])   # duas leituras: uma fora de tolerância, outra dentro
    f.compass = FakeCompass([50, 0])
    f.cfg["auto_camera"] = False  # aqui queremos testar a pausa manual, não a correção sozinha
    f.cfg["timings"]["recovery_wait_sec"] = 999
    waited = []
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: waited.append(True))
    f.check_camera()
    assert waited == [True]  # só espera quando a câmera realmente saiu do lugar e voltou


def test_camera_sem_desvio_nao_espera_mouse_livre(monkeypatch):
    f = FakeFisher([None])
    f.compass = FakeCompass([0])
    called = []
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: called.append(True))
    f.check_camera()
    assert called == []  # sem pausa nenhuma: não precisa esperar nada extra


# ---------------------------------------------------------------- menu principal (servidor reiniciou)

def test_recuperacao_no_menu_principal_para_de_vez_e_avisa(monkeypatch):
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: None)
    monkeypatch.setattr(cycle.screen, "release_right_button", lambda: None)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: True))
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.cfg["discord"]["notify_problems"] = True
    f.cfg["timings"]["recovery_wait_sec"] = 999  # se esperasse os 30 s, o teste travaria
    with pytest.raises(cycle.StopRun):
        f._recover("não consegui equipar a vara (tecla 3)", object())
    assert f.stop_for_good  # reiniciar sozinho não adianta: precisa alguém entrar no jogo
    assert f.recoveries == 0
    assert len(f.notifier.sent) == 1 and "menu principal" in f.notifier.sent[0][0]
    assert f.notifier.sent[0][1] is True  # marca você


def test_recuperacao_fora_do_menu_segue_normal(monkeypatch):
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: None)
    monkeypatch.setattr(cycle.screen, "release_right_button", lambda: None)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: False))
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.cfg["timings"]["recovery_wait_sec"] = 0
    f._recover("teste", object())
    assert f.recoveries == 1 and not f.stop_for_good


def test_bussola_sumida_por_causa_do_menu_para_em_vez_de_pausar_para_sempre(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    checks = []
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: checks.append(img) or len(checks) >= 2))
    f = FakeFisher([None] * 50)
    f.compass = FakeCompass([None] * 50)
    f.cfg["auto_camera"] = False  # testando a checagem de menu na pausa, não a varredura
    f.notifier = FakeNotifier()
    with pytest.raises(cycle.StopRun):
        f.check_camera()
    assert f.stop_for_good


def test_camera_girada_nao_procura_menu(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: True)
    called = []
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: called.append(True) or False))
    f = FakeFisher([None] * 3)
    f.compass = FakeCompass([40, 40, 0])  # bússola achada, só girada: não é o menu
    f.cfg["auto_camera"] = False  # testando a pausa manual (sem menu), não a correção sozinha
    f.check_camera()
    assert called == []


def test_aviso_nunca_visto_segura_quase_continuo_como_antes(collect_env):
    """Revisão de 24/09: às cegas do começo ao fim, o T só pode soltar para reapertar
    (sem buraco de ~1 s, que poderia zerar a coleta), e cada aperto dura o mínimo."""
    f, env = collect_env
    env["prompt"] = lambda t: False
    f._hold_t([], 12.0, "da vara")
    keys = env["keys"]
    presses = [t for kind, _, t in keys if kind == "press"]
    releases = [t for kind, _, t in keys if kind == "release"]
    assert presses and presses[0] <= 1.1
    for rel, nxt in zip(releases, presses[1:]):
        assert nxt - rel <= 0.2, (rel, nxt)
    for p, rel in zip(presses, releases[:-1]):
        assert rel - p >= cycle.MIN_T_HOLD_SEC


# ---------------------------------------------------------------- anti-inatividade

def test_anti_idle_so_manda_apos_o_intervalo_configurado(monkeypatch):
    f = FakeFisher([])
    f.hwnd = 1
    f.cfg["timings"]["anti_idle_sec"] = 10.0
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: True)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    last = f._anti_idle_tick(0.0, 5.0)   # ainda não passou o intervalo
    assert last == 0.0 and nudges == []
    last = f._anti_idle_tick(last, 10.0)  # completou o intervalo: manda e reinicia a contagem
    assert last == 10.0 and nudges == [True]


def test_anti_idle_nunca_manda_com_roblox_fora_da_frente(monkeypatch):
    f = FakeFisher([])
    f.hwnd = 1
    f.cfg["timings"]["anti_idle_sec"] = 10.0
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: False)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    f._anti_idle_tick(0.0, 10.0)
    assert nudges == []


def test_anti_idle_sem_hwnd_nao_confere_janela_nem_manda(monkeypatch):
    f = FakeFisher([])
    f.hwnd = None
    f.cfg["timings"]["anti_idle_sec"] = 10.0
    called = []
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: called.append(True) or True)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    f._anti_idle_tick(0.0, 10.0)
    assert called == [] and nudges == []


def test_anti_idle_zero_desliga(monkeypatch):
    f = FakeFisher([])
    f.hwnd = 1
    f.cfg["timings"]["anti_idle_sec"] = 0
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: True)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    last = f._anti_idle_tick(0.0, 999.0)
    assert nudges == [] and last == 0.0


def test_recuperacao_manda_anti_idle_durante_espera_longa(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: None)
    monkeypatch.setattr(cycle.screen, "release_right_button", lambda: None)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: False))
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: True)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    f = FakeFisher([])
    f.hwnd = 1
    f.notifier = FakeNotifier()
    f.cfg["timings"]["recovery_wait_sec"] = 30.0
    f.cfg["timings"]["anti_idle_sec"] = 12.0
    f._recover("teste", None)
    assert len(nudges) >= 2  # espera de 30s com anti-idle a cada 12s: manda mais de uma vez


def test_ponto_fora_do_monitor_manda_anti_idle_na_espera(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.window, "is_foreground", lambda hwnd: True)
    nudges = []
    monkeypatch.setattr(cycle.screen, "anti_idle_nudge", lambda: nudges.append(True))
    f = FakeFisher([])
    f.hwnd = 1
    f.cfg["timings"]["recovery_wait_sec"] = 999
    f.cfg["timings"]["anti_idle_sec"] = 3.0
    monitor_calls = []

    def fake_on_monitor(x, y):
        monitor_calls.append((x, y))
        return len(monitor_calls) > 15  # demora bastante para "voltar" (espera fica longa)

    monkeypatch.setattr(cycle.screen, "on_monitor", fake_on_monitor)
    f.rect = lambda: cycle.window.Rect(0, 0, 100, 100)
    f.cfg["cast_point"] = {"x": 0.5, "y": 0.5}
    f._wait_cast_point_on_monitor()
    assert nudges  # a pausa é maior que o intervalo de anti-inatividade: mandou pelo menos uma vez


# ---------------------------------------------------------------- câmera automática

class FakeCompassAuto:
    """Bússola de mentira que reage de verdade ao arrasto, como uma câmera física: o
    ganho/sentido "real" é escondido do código testado, que só descobre pela resposta."""

    def __init__(self, drift0, real_gain=1 / 3, none_calls=0):
        self.ready = True
        self.pos = float(drift0)
        self.real_gain = real_gain     # px de bússola corrigidos por px de arrasto (sinal real)
        self.drags = []
        self._none_calls = none_calls  # 1ªs leituras "sem bússola" (simula câmera fora da faixa)
        self._reads = 0

    def apply_drag(self, dx):
        self.drags.append(dx)
        self.pos -= dx * self.real_gain

    def drift_px(self, img):
        self._reads += 1
        if self._reads <= self._none_calls:
            return None
        return int(round(self.pos))


@pytest.fixture
def auto_camera_env(monkeypatch):
    """check_camera/_auto_fix_camera sem tela de verdade: o arrasto vira `apply_drag`
    na bússola falsa, que responde de acordo com o ganho "real" escondido no teste."""
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)

    def make(compass, frames=200):
        monkeypatch.setattr(cycle.screen, "right_drag", lambda dx: compass.apply_drag(dx))
        f = FakeFisher([None] * frames)
        f.compass = compass
        return f
    return make


def test_camera_converge_mesmo_com_ganho_inicial_errado(auto_camera_env):
    compass = FakeCompassAuto(drift0=100, real_gain=0.05)  # precisa de arrastos bem maiores
    f = auto_camera_env(compass)
    assert f._camera_gain == cycle.AUTO_CAMERA_DEFAULT_GAIN  # chute inicial, ainda não aprendeu
    ok = f._auto_fix_camera(tol=6, drift=100)
    assert ok is True
    assert abs(compass.pos) <= 6
    assert f._camera_gain != cycle.AUTO_CAMERA_DEFAULT_GAIN  # aprendeu um ganho diferente
    assert len(compass.drags) <= cycle.AUTO_CAMERA_MAX_TRIES


def test_camera_converge_com_sentido_invertido(auto_camera_env):
    # ganho "real" negativo: arrastar do jeito que o chute inicial manda piora o desvio
    compass = FakeCompassAuto(drift0=80, real_gain=-0.2)
    f = auto_camera_env(compass)
    ok = f._auto_fix_camera(tol=6, drift=80)
    assert ok is True
    assert abs(compass.pos) <= 6
    assert f._camera_gain < 0  # aprendeu que o sentido é o oposto do chute


def test_camera_ja_dentro_da_tolerancia_nao_arrasta(auto_camera_env):
    compass = FakeCompassAuto(drift0=4, real_gain=0.5)
    f = auto_camera_env(compass)
    ok = f._auto_fix_camera(tol=6, drift=4)
    assert ok is True
    assert compass.drags == []  # já estava dentro da tolerância: não mexeu em nada


def test_camera_varre_quando_bussola_nao_encontrada(auto_camera_env):
    # bússola só aparece depois de algumas voltas da varredura
    compass = FakeCompassAuto(drift0=50, real_gain=0.4, none_calls=5)
    f = auto_camera_env(compass)
    ok = f._auto_fix_camera(tol=6, drift=None)
    assert ok is True
    assert abs(compass.pos) <= 6
    # conferiu de novo antes de girar e varreu até achar
    assert len(compass.drags) >= 5 - cycle.AUTO_CAMERA_RECHECKS


def test_camera_desiste_da_varredura_apos_a_volta_inteira(auto_camera_env):
    compass = FakeCompassAuto(drift0=50, real_gain=0.4, none_calls=999)  # nunca aparece
    f = auto_camera_env(compass)
    ok = f._auto_fix_camera(tol=6, drift=None)
    assert ok is False
    assert len(compass.drags) == cycle.AUTO_CAMERA_SWEEP_STEPS  # tentou a volta inteira, não mais


def test_camera_desiste_do_ajuste_fino_e_cai_na_pausa(monkeypatch):
    """Ganho aprendido zera o movimento (drag sempre 0): desiste sem travar."""
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    f = FakeFisher([None] * 5)
    f.compass = FakeCompass([80])  # só a 1ª leitura, feita pelo check_camera
    f._camera_gain = 0.0  # nenhum arrasto corrige nada: precisa desistir, não travar
    paused = []
    monkeypatch.setattr(f, "_pause_for_camera", lambda tol, drift, img: paused.append(drift))
    f.check_camera()
    assert paused == [80]  # caiu na pausa manual com o desvio original


def test_camera_falha_e_cai_na_pausa_quando_bussola_nunca_aparece(monkeypatch):
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    drags = []
    monkeypatch.setattr(cycle.screen, "right_drag", lambda dx: drags.append(dx))
    f = FakeFisher([None] * 20)
    f.compass = FakeCompass([None] * 20)  # nunca acha, nem variando
    paused = []
    monkeypatch.setattr(f, "_pause_for_camera", lambda tol, drift, img: paused.append((tol, drift)))
    f.check_camera()
    assert paused == [(6, None)]
    assert len(drags) == cycle.AUTO_CAMERA_SWEEP_STEPS  # varreu a volta inteira e desistiu


def test_camera_auto_corrigida_espera_botao_direito_soltar(monkeypatch):
    compass = FakeCompassAuto(drift0=50, real_gain=0.5)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.screen, "right_drag", lambda dx: compass.apply_drag(dx))
    waited = []
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: waited.append(True))
    f = FakeFisher([None] * 20)
    f.compass = compass
    f.check_camera()
    assert waited == [True]  # convergiu sozinho: ainda espera o botão direito soltar


def test_auto_camera_desligado_nunca_arrasta(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cycle, "time", clock)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    drags = []
    monkeypatch.setattr(cycle.screen, "right_drag", lambda dx: drags.append(dx))
    monkeypatch.setattr(cycle.screen, "wait_mouse_free", lambda **kw: None)
    f = FakeFisher([None, None])
    f.compass = FakeCompass([50, 0])
    f.cfg["auto_camera"] = False
    f.cfg["timings"]["recovery_wait_sec"] = 999
    f.check_camera()
    assert drags == []  # desligado na config: nunca tenta girar sozinho


def test_recover_solta_botao_direito(monkeypatch):
    monkeypatch.setattr(cycle.screen, "release_key", lambda k: None)
    monkeypatch.setattr(cycle.screen.MouseButton, "release", lambda self: None)
    monkeypatch.setattr(cycle.logbook, "save_evidence", lambda img, reason: None)
    monkeypatch.setattr(cycle.relog_bridge, "lost_game_screen", _as_lost(lambda img: False))
    released = []
    monkeypatch.setattr(cycle.screen, "release_right_button", lambda: released.append(True))
    f = FakeFisher([])
    f.notifier = FakeNotifier()
    f.cfg["timings"]["recovery_wait_sec"] = 0
    f._recover("teste", None)
    assert released == [True]  # nunca deixa o botão direito preso, mesmo fora da câmera


def test_camera_poe_o_cursor_no_ponto_de_lancamento_antes_de_girar(auto_camera_env, monkeypatch):
    """O arrasto do botão direito vai para a janela embaixo do cursor: se ele estiver em cima
    da janela da macro (ou longe, depois de um relog), a câmera do jogo não gira."""
    compass = FakeCompassAuto(drift0=40, real_gain=0.5)
    f = auto_camera_env(compass)
    f.cfg["cast_point"] = {"x": 0.5, "y": 0.25}
    f.rect = lambda: cycle.window.Rect(0, 0, 100, 100)
    events = []
    monkeypatch.setattr(cycle.screen, "move_to", lambda x, y: events.append(("move", x, y)))
    monkeypatch.setattr(cycle.screen, "right_drag", lambda dx: events.append(("drag", dx)) or compass.apply_drag(dx))
    assert f._auto_fix_camera(tol=6, drift=40)
    assert events[0] == ("move", 50, 25)
    assert all(e[0] == "drag" for e in events[1:])


def test_ganho_nao_muda_com_movimento_minusculo():
    """Revisão de 24/09: bússola mexendo 1 px depois de um arrasto grande não é medida
    confiável; aprender com ela faria o ganho explodir e a câmera passar do ponto."""
    f = FakeFisher([])
    f._camera_gain = 3.0
    f._learn_gain(drift_before=50, dx=300, drift_after=49)
    assert f._camera_gain == 3.0


def test_ganho_volta_ao_padrao_quando_o_ajuste_falha(auto_camera_env):
    compass = FakeCompassAuto(drift0=50, real_gain=0.4, none_calls=999)
    f = auto_camera_env(compass)
    f._camera_gain = 42.0
    assert f._auto_fix_camera(tol=6, drift=None) is False
    assert f._camera_gain == cycle.AUTO_CAMERA_DEFAULT_GAIN


def test_bussola_sumida_um_quadro_nao_varre(auto_camera_env):
    """Uma notificação cobrindo a bússola por um instante não pode girar a câmera inteira."""
    compass = FakeCompassAuto(drift0=0, real_gain=0.4, none_calls=1)
    f = auto_camera_env(compass)
    assert f._auto_fix_camera(tol=6, drift=None) is True
    assert compass.drags == []


# ---------------------------------------------------------------- setar o spawn

@pytest.fixture
def spawn_env(monkeypatch):
    calls, marked = [], []

    def make(result_ok=True, **relog_over):
        f = FakeFisher([])
        f.cfg["relog"].update(relog_over)
        f.spawn_auto_allowed, f._fished_ok = True, True
        f.cb.spawn_set = lambda ok: marked.append(ok)
        f.notifier = FakeNotifier()
        monkeypatch.setattr(cycle.relog_bridge, "set_spawn",
                            lambda fisher: calls.append(True) or cycle.spawn.SpawnResult(result_ok, "x"))
        return f
    return make, calls, marked


def test_seta_o_spawn_sozinho_uma_vez_quando_falta(spawn_env):
    make, calls, marked = spawn_env
    f = make(enabled=True, has_spawn_gamepass=True, spawn_set=False)
    f._set_spawn_if_needed()
    f._set_spawn_if_needed()
    assert calls == [True] and marked == [True]
    assert f.cfg["relog"]["spawn_set"] is True


def test_falhou_nao_fica_tentando_a_cada_ciclo(spawn_env):
    make, calls, marked = spawn_env
    f = make(result_ok=False, enabled=True, has_spawn_gamepass=True, spawn_set=False)
    f._set_spawn_if_needed()
    f._set_spawn_if_needed()
    assert calls == [True] and marked == [False]


def test_sem_gamepass_ou_ja_setado_nao_mexe(spawn_env):
    make, calls, _ = spawn_env
    for over in (dict(enabled=True, has_spawn_gamepass=False), dict(enabled=True, has_spawn_gamepass=True,
                                                                     spawn_set=True), dict(enabled=False)):
        make(**over)._set_spawn_if_needed()
    assert calls == []


def test_pedido_pelo_botao_seta_mesmo_ja_setado(spawn_env):
    make, calls, marked = spawn_env
    f = make(enabled=False, has_spawn_gamepass=True, spawn_set=True)
    f.spawn_requested = True
    f._set_spawn_if_needed()
    assert calls == [True] and marked == [True] and f.spawn_requested is False


def test_spawn_automatico_espera_o_primeiro_peixe(spawn_env):
    make, calls, _ = spawn_env
    f = make(enabled=True, has_spawn_gamepass=True, spawn_set=False)
    f._fished_ok = False
    f._set_spawn_if_needed()
    assert calls == []


def test_reinicio_sozinho_nunca_seta_o_spawn(spawn_env):
    """Revisão de 24/09: depois de parar sozinha, o personagem pode estar em outro lugar."""
    make, calls, _ = spawn_env
    f = make(enabled=True, has_spawn_gamepass=True, spawn_set=False)
    f.spawn_auto_allowed = False
    f._set_spawn_if_needed()
    assert calls == []


def test_discord_recebe_nome_raridade_e_imagem_da_ficha_do_catalogo(tmp_path, monkeypatch):
    """Pedido de 24/09: o aviso usa a ficha do catálogo (nome certo, imagem, raridade)."""
    import json

    import cv2
    import numpy as np

    from catalog import Catalog
    from loot import Loot
    from session import Session
    shared = tmp_path / "catalogo"
    (shared / "imagens").mkdir(parents=True)
    cv2.imwrite(str(shared / "imagens" / "lost-cape.png"), np.full((30, 90, 3), 77, np.uint8))
    item = {"name": "Lost Cape", "slug": "lost-cape", "image": "imagens/lost-cape.png", "rarity": "mythic",
            "rarity_votes": {}, "aliases": []}
    (shared / "itens.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    sent, shown = [], []
    f = FakeFisher([True])
    f.catalog = Catalog(shared, tmp_path / "catalogo_local")
    f.session = Session(log_dir=tmp_path)
    f.notifier = type("N", (), {"send_loot": lambda self, r: sent.append(r)})()
    f.cb.loot = lambda items, snap: shown.append(snap)
    f.cfg["timings"]["after_minigame_sec"] = 0
    f.cfg["timings"]["after_collect_sec"] = 0
    live = np.full((20, 60, 3), 200, np.uint8)
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img, **kw: [])
    monkeypatch.setattr(cycle.loot_mod, "item_snapshot", lambda img, it: live)
    f._hold_t = lambda before, budget, where: ([Loot("LO$t Cape", 1, "common", (0, 0, 1, 1))], None)
    got = f.collect()
    assert [(i.name, i.rarity) for i in got] == [("Lost Cape", "mythic")]
    report = sent[0]
    assert (report.name, report.rarity) == ("Lost Cape", "mythic")
    assert report.image.shape == (30, 90, 3) and int(report.image[0, 0, 0]) == 77  # imagem da ficha
    assert shown[0].shape == (30, 90, 3)  # a janela da macro mostra a mesma imagem



def test_toda_espera_da_pesca_da_sinal_de_vida_ao_cao_de_guarda():
    """Pausas (bússola, Roblox fora da frente) também batem: só travamento de verdade fica mudo."""
    beats = []
    f = FakeFisher([True])
    f.on_beat = lambda: beats.append(1)
    f.sleep(0.05)
    assert len(beats) >= 2


def _only_fails_casting(f):
    for name in ("_set_spawn_if_needed", "_maybe_check_baits", "ensure_rod", "check_camera", "cast"):
        setattr(f, name, lambda: None)
    f.minigame = lambda: False
    f._notify = lambda text, ping=True: f.notified.append(text)
    f.notified = []


def test_depois_do_relog_sem_peixe_para_e_avisa_do_spawn():
    """Ewerton 25/09: spawn setado longe da água; depois do relog lançou 40x sem peixe (8
    recuperações). Sem nenhum peixe desde o relog, 5 lançamentos vazios = nasceu longe da água."""
    f = FakeFisher([True])
    _only_fails_casting(f)
    f.after_relog = True
    for _ in range(9):
        try:
            f.one_cycle()
        except cycle.Recoverable:
            pass
    with pytest.raises(cycle.StopRun) as exc:
        f.one_cycle()
    assert "spawn" in str(exc.value) and f.stop_for_good
    assert any("spawn" in t for t in f.notified)


def test_sem_relog_continua_sendo_uma_recuperacao_comum():
    f = FakeFisher([True])
    _only_fails_casting(f)
    limit = int(f.cfg["limits"]["max_failed_casts"])
    for _ in range(limit - 1):
        f.one_cycle()
    with pytest.raises(cycle.Recoverable):
        f.one_cycle()
    assert not f.stop_for_good
def test_nome_que_nao_existe_nao_vai_para_janela_historico_nem_discord(tmp_path, monkeypatch):
    """25/09: "xg•.ollec" (pedaço do botão Collect) e "Clovurn Fish" apareciam como itens."""
    import json

    import numpy as np

    from catalog import Catalog
    from loot import Loot
    from session import Session
    shared = tmp_path / "catalogo"
    shared.mkdir()
    item = {"name": "Clown Fish", "slug": "clown-fish", "image": None, "rarity": "rare",
            "rarity_votes": {}, "aliases": []}
    (shared / "itens.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
    sent, shown = [], []
    f = FakeFisher([True, True])
    f.catalog = Catalog(shared, tmp_path / "catalogo_local")
    f.session = Session(log_dir=tmp_path)
    f.notifier = type("N", (), {"send_loot": lambda self, r: sent.append(r)})()
    f.cb.loot = lambda items, snap: shown.append([i.name for i in items])
    f.cfg["timings"]["after_minigame_sec"] = 0
    f.cfg["timings"]["after_collect_sec"] = 0
    monkeypatch.setattr(cycle.loot_mod, "read_popups", lambda img, **kw: [])
    monkeypatch.setattr(cycle.loot_mod, "item_snapshot", lambda img, it: np.zeros((20, 60, 3), np.uint8))
    box = (0, 0, 1, 1)
    f._hold_t = lambda before, budget, where: ([Loot("Clov.tn Fish", 1, "rare", box),
                                                Loot("xg•.ollec", 1, "common", box),
                                                Loot("Clovurn Fish", 1, "rare", box, lone=True)], None)
    got = f.collect()
    assert [i.name for i in got] == ["Clown Fish"]
    assert [r.name for r in sent] == ["Clown Fish"]
    assert shown == [["Clown Fish"]]
    assert f.session.catches == 1



def test_depois_do_relog_espera_10_lancamentos_vazios():
    """Pedido de 25/09: 10 lançamentos sem peixe depois do relog (não 5) antes de parar."""
    f = FakeFisher([True])
    _only_fails_casting(f)
    f.after_relog = True
    recoveries = 0
    for _ in range(9):
        try:
            f.one_cycle()
        except cycle.Recoverable:
            recoveries += 1
    assert recoveries == 1  # nos 5 primeiros vazios ainda tenta se recuperar
    with pytest.raises(cycle.StopRun):
        f.one_cycle()


def test_isca_gasta_quando_o_minigame_comeca():
    """Pedido de 25/09: no jogo a isca é gasta quando o minigame começa (pegando ou não)."""
    f = FakeFisher([True])
    spent = []
    f._baits_on = lambda: True
    f.baits = type("B", (), {"consume": lambda self, sec, inf: spent.append(1) or "Fish Head",
                             "save": lambda self, p: None, "summary": lambda self, inf: "",
                             "warning": False})()
    f.bait_path = None
    f.session = type("S", (), {"record_bait": lambda self, n: spent.append(n)})()
    f._spend_bait()
    assert spent == [1, "Fish Head"]
