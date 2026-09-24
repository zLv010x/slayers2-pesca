"""Máquina de estados do Relogger com telas falsas (sem OCR/imagem de verdade):
fluxo VIP e por nick, código sem reconexão, dialog sem botão, timeouts e o
solta-sempre do JOIN segurado."""
import pytest

import relog
from relog import DEFAULTS, Relogger, Screen

RECONNECT_POS = (1073, 621)
PLAY_POS = (90, 598)
CARD_POS = (390, 430)
OWNER_POS = (960, 877)
JOIN_POS = (960, 930)
JOIN_PRIVATE_POS = (960, 900)
# VIP de verdade (vídeo do usuário): segurando o JOIN, o botão vira "JOIN PRIVATE" (o OCR
# pode nem ler, dourado) e depois de ~0,8 s começa a carregar; soltar antes cancela.
VIP_TEXT_CHANGE_SEC = 0.4
VIP_LOAD_SEC = 0.8
LOAD_TO_GAME_SEC = 1.0

# Telas falsas: a chave é o "frame" que FakeGame devolve (só o nome do estado).
SCREENS = {
    "disconnected": Screen(kind="disconnected", reconnect_pos=RECONNECT_POS,
                            leave_pos=(929, 621), error_code=278),
    "disconnected_264": Screen(kind="disconnected", reconnect_pos=RECONNECT_POS, error_code=264),
    "disconnected_sem_reconnect": Screen(kind="disconnected", reconnect_pos=None, leave_pos=(900, 621)),
    "main_menu": Screen(kind="main_menu", play_pos=PLAY_POS),
    "server_select": Screen(kind="server_select", card_pos=CARD_POS),
    "server_card": Screen(kind="server_card", join_pos=JOIN_POS, owner_field_pos=OWNER_POS),
    "server_card_com_join_private": Screen(kind="server_card", join_pos=JOIN_POS, owner_field_pos=OWNER_POS,
                                            join_private_pos=JOIN_PRIVATE_POS),
    "loading": Screen(kind="loading"),
}


def _fake_classify(frame, cfg=None):
    return SCREENS.get(frame, Screen(kind="unknown"))


class FakeFrame(str):
    """String (nome do estado) que também parece um frame de verdade (`.shape`)."""
    shape = (1004, 1918, 3)


@pytest.fixture(autouse=True)
def _sem_ocr_de_verdade(monkeypatch):
    """Todos os testes deste arquivo usam telas falsas, nunca OCR de verdade."""
    monkeypatch.setattr(relog, "classify", _fake_classify)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, sec: float) -> None:
        self.t += sec


class FakeGame:
    """Simula o jogo reagindo às ações da macro (clique muda de tela etc.)."""

    def __init__(self, start: str, server_mode: str):
        self.kind = start
        self.server_mode = server_mode
        self.clicks: list[tuple[int, int]] = []
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.mouse_events: list[tuple] = []
        self.status_msgs: list[str] = []
        self.in_game_calls = 0
        self.clock = FakeClock()
        self._hold_start: float | None = None
        self._loaded_at: float | None = None

    # --- interface `actions` esperada pelo Relogger ---------------------------
    def grab(self):
        now = self.clock.now()
        if self._hold_start is not None and self.server_mode == "vip":
            held = now - self._hold_start
            if held >= VIP_LOAD_SEC:
                self.kind, self._loaded_at = "loading", now
            elif held >= VIP_TEXT_CHANGE_SEC:
                self.kind = "join_private_segurando"  # tela que o classify não reconhece
        elif self.kind == "loading" and self._loaded_at is not None and now - self._loaded_at >= LOAD_TO_GAME_SEC:
            self.kind = "ingame"
        return 0, 0, FakeFrame(self.kind)

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        self._on_click(x, y)

    def _on_click(self, x: int, y: int) -> None:
        pos = (x, y)
        if self.kind == "disconnected" and pos == RECONNECT_POS:
            self.kind = "main_menu"
        elif self.kind == "main_menu" and pos == PLAY_POS:
            self.kind = "server_select"
        elif self.kind == "server_select" and pos == CARD_POS:
            self.kind = "server_card"
        elif self.kind.startswith("server_card") and pos == JOIN_PRIVATE_POS:
            self.kind = "ingame"
        # clicar no campo de nick/VIP ou "fora dele" não muda a tela por si só

    def mouse_down(self, x: int, y: int) -> None:
        self.mouse_events.append(("down", x, y, self.clock.now()))
        if self.kind.startswith("server_card") and (x, y) == JOIN_POS:
            self._hold_start = self.clock.now()

    def mouse_up(self) -> None:
        self.mouse_events.append(("up", self.clock.now()))
        if self._hold_start is not None and self.kind != "loading":
            self.kind = "server_card"  # soltou antes de carregar: o jogo cancela
        self._hold_start = None

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press(self, key: str) -> None:
        self.pressed.append(key)
        if key == "enter" and self.kind == "server_card" and self.server_mode == "nick":
            self.kind = "server_card_com_join_private"

    def sleep(self, sec: float) -> None:
        self.clock.sleep(sec)

    def now(self) -> float:
        return self.clock.now()

    def in_game(self, frame) -> bool:
        self.in_game_calls += 1
        return frame == "ingame"

    def status(self, msg: str) -> None:
        self.status_msgs.append(msg)


class StuckGame(FakeGame):
    """A tela nunca reage a clique: serve para testar os timeouts."""

    def _on_click(self, x: int, y: int) -> None:
        pass


def _cfg(**over):
    return {**DEFAULTS, "enabled": True, **over}


def test_fluxo_vip_a_partir_do_disconnected():
    game = FakeGame(start="disconnected", server_mode="vip")
    cfg = _cfg(server_mode="vip", hold_join_sec=3.0)
    result = Relogger(cfg, game).run()
    assert result.ok and result.reason == "ok"
    # com VIP é só clicar no mundo e segurar o JOIN (sem mexer no campo do nick)
    assert game.clicks == [RECONNECT_POS, PLAY_POS, CARD_POS]
    downs = [e for e in game.mouse_events if e[0] == "down"]
    ups = [e for e in game.mouse_events if e[0] == "up"]
    assert len(downs) == 1 and len(ups) == 1
    held = ups[0][1] - downs[0][3]
    assert VIP_LOAD_SEC <= held < cfg["hold_join_sec"]  # soltou quando carregou, não antes nem no limite
    assert game.in_game_calls >= 1


def test_vip_nao_solta_quando_o_botao_vira_join_private():
    """Revisão de 24/09: soltar quando a tela "mudava" cancelava a entrada, porque o
    botão vira JOIN PRIVATE no meio da segurada."""
    game = FakeGame(start="server_card", server_mode="vip")
    relogger = Relogger(_cfg(server_mode="vip", hold_join_sec=3.0), game)
    relogger._hold_join(*JOIN_POS)
    assert game.kind == "loading"


def test_vip_solta_no_limite_se_nunca_carregar():
    class NeverLoads(FakeGame):
        def grab(self):
            return 0, 0, FakeFrame("join_private_segurando")
    game = NeverLoads(start="server_card", server_mode="vip")
    relogger = Relogger(_cfg(server_mode="vip", hold_join_sec=3.0), game)
    relogger._hold_join(*JOIN_POS)
    down, up = game.mouse_events
    assert up[1] - down[3] >= 3.0


def test_fluxo_nick_a_partir_do_menu_pula_o_reconnect():
    # já está no menu principal: não faz sentido nem existe um Reconnect pra clicar.
    game = FakeGame(start="main_menu", server_mode="nick")
    cfg = _cfg(server_mode="nick", owner_nick="Fulano123")
    result = Relogger(cfg, game).run()
    assert result.ok and result.reason == "ok"
    assert RECONNECT_POS not in game.clicks
    assert game.clicks[:3] == [PLAY_POS, CARD_POS, OWNER_POS]
    assert game.typed == ["Fulano123"]
    assert game.pressed == ["enter"]
    assert JOIN_PRIVATE_POS in game.clicks
    assert not any(e[0] == "down" for e in game.mouse_events)  # nick não segura JOIN


def test_clique_no_menu_principal_respeita_cooldown_entre_leituras_iguais():
    """3 leituras seguidas da mesma tela geram 1 clique só; depois do cooldown, clica de novo."""
    game = FakeGame(start="main_menu", server_mode="vip")
    relogger = Relogger(_cfg(), game)
    screen, frame = SCREENS["main_menu"], FakeFrame("main_menu")
    relogger._on_main_menu(screen, frame)
    game.clock.sleep(1.0)
    relogger._on_main_menu(screen, frame)
    game.clock.sleep(1.0)
    relogger._on_main_menu(screen, frame)
    assert game.clicks == [PLAY_POS]
    game.clock.sleep(relog.CLICK_COOLDOWN_SEC)
    relogger._on_main_menu(screen, frame)
    assert game.clicks == [PLAY_POS, PLAY_POS]


def test_codigo_sem_reconexao_nao_clica_em_nada():
    game = FakeGame(start="disconnected_264", server_mode="vip")
    result = Relogger(_cfg(), game).run()
    assert not result.ok
    assert result.reason == "codigo_sem_reconexao"
    assert result.error_code == 264
    assert game.clicks == []


def test_dialog_sem_botao_reconnect_nao_reconecta():
    game = FakeGame(start="disconnected_sem_reconnect", server_mode="vip")
    result = Relogger(_cfg(), game).run()
    assert not result.ok
    assert result.reason == "sem_botao_reconnect"
    assert game.clicks == []


def test_desabilitado_nao_faz_nada():
    game = FakeGame(start="disconnected", server_mode="vip")
    result = Relogger(_cfg(enabled=False), game).run()
    assert not result.ok and result.reason == "desabilitado"
    assert game.clicks == []


def test_modo_de_servidor_invalido_falha_sem_tentar():
    game = FakeGame(start="main_menu", server_mode="vip")
    result = Relogger(_cfg(server_mode="turbo"), game).run()
    assert not result.ok and result.reason == "modo_servidor_invalido"
    assert game.clicks == []


def test_timeout_de_etapa_vira_falha_com_motivo():
    game = StuckGame(start="server_select", server_mode="vip")
    cfg = _cfg(step_timeout_sec=1, total_timeout_sec=600)
    result = Relogger(cfg, game).run()
    assert not result.ok
    assert result.reason == "timeout_etapa"
    assert len(game.clicks) >= 1


def test_timeout_total_vira_falha_com_motivo():
    game = StuckGame(start="server_select", server_mode="vip")
    cfg = _cfg(step_timeout_sec=600, total_timeout_sec=relog.POLL_SEC)
    result = Relogger(cfg, game).run()
    assert not result.ok
    assert result.reason == "timeout_total"


class NeverConfirmsActions:
    """in_game() sempre False: só sobra o "unknown" sustentado por settle_sec como
    prova de que voltou ao jogo. A sequência de telas é fixa (não reage a clique);
    o último item se repete indefinidamente."""

    def __init__(self, sequence: list[str]):
        self.sequence = sequence
        self.idx = 0
        self.clicks: list[tuple[int, int]] = []
        self.mouse_events: list[tuple] = []
        self.typed: list[str] = []
        self.pressed: list[str] = []
        self.status_msgs: list[str] = []
        self.clock = FakeClock()

    def grab(self):
        frame = self.sequence[min(self.idx, len(self.sequence) - 1)]
        self.idx += 1
        return 0, 0, FakeFrame(frame)

    def click(self, x, y):
        self.clicks.append((x, y))

    def mouse_down(self, x, y):
        self.mouse_events.append(("down", x, y))

    def mouse_up(self):
        self.mouse_events.append(("up",))

    def type_text(self, text):
        self.typed.append(text)

    def press(self, key):
        self.pressed.append(key)

    def sleep(self, sec):
        self.clock.sleep(sec)

    def now(self):
        return self.clock.now()

    def in_game(self, frame):
        return False

    def status(self, msg):
        self.status_msgs.append(msg)


def test_volta_ao_jogo_por_settle_apos_sequencia_de_telas_conhecidas():
    # menu -> server_select -> server_card -> loading -> unknown (repete): sem in_game()
    # confirmar, só conta como "ok" depois de settle_sec seguidos em tela desconhecida.
    actions = NeverConfirmsActions(["main_menu", "server_select", "server_card", "loading", "unknown"])
    cfg = _cfg(server_mode="nick", owner_nick="Fulano", settle_sec=1.0)
    result = Relogger(cfg, actions).run()
    assert result.ok and result.reason == "ok"
    polls_ate_unknown = 4  # main_menu, server_select, server_card, loading
    assert actions.idx >= polls_ate_unknown + round(1.0 / relog.POLL_SEC)


def test_volta_ao_jogo_por_settle_desde_o_comeco():
    # relog chamado com o jogo já normal: nunca passa por nenhuma tela conhecida.
    actions = NeverConfirmsActions(["unknown"])
    cfg = _cfg(settle_sec=1.0)
    result = Relogger(cfg, actions).run()
    assert result.ok and result.reason == "ok"
    assert actions.idx >= round(1.0 / relog.POLL_SEC)


def test_tela_carregando_so_avisa_e_continua_olhando():
    game = FakeGame(start="loading", server_mode="vip")
    relogger = Relogger(_cfg(), game)
    result = relogger._step(Screen(kind="loading"), FakeFrame("loading"))
    assert result is None
    assert any("arregando" in m for m in game.status_msgs)


def test_hold_solta_mesmo_com_excecao():
    class FakeHoldActions:
        def __init__(self):
            self.t = 0.0
            self.mouse: list[str] = []
            self.grabs = 0

        def now(self):
            return self.t

        def sleep(self, sec):
            self.t += sec

        def mouse_down(self, x, y):
            self.mouse.append("down")

        def mouse_up(self):
            self.mouse.append("up")

        def grab(self):
            self.grabs += 1
            raise RuntimeError("falha simulada durante o hold")

    actions = FakeHoldActions()
    relogger = Relogger(_cfg(hold_join_sec=5.0), actions)
    with pytest.raises(RuntimeError):
        relogger._hold_join(960, 930)
    assert actions.mouse == ["down", "up"]


def test_hold_solta_cedo_se_a_tela_mudar_antes_da_hora():
    class ChangingActions:
        def __init__(self):
            self.t = 0.0
            self.mouse: list[str] = []
            self.grabs = 0

        def now(self):
            return self.t

        def sleep(self, sec):
            self.t += sec

        def mouse_down(self, x, y):
            self.mouse.append("down")

        def mouse_up(self):
            self.mouse.append("up")

        def grab(self):
            self.grabs += 1
            # muda de tela já na primeira olhada: não devia esperar o hold_join_sec inteiro
            return 0, 0, "loading"

    actions = ChangingActions()
    relogger = Relogger(_cfg(hold_join_sec=5.0), actions)
    relogger._hold_join(960, 930)
    assert actions.mouse == ["down", "up"]
    assert actions.t < 5.0
