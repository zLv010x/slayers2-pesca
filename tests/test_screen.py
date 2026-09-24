"""Testes de src/screen.py: mover o mouse até o ponto de lançamento e detectar
quando ele está "em uso" (o usuário mexendo ou um botão preso girando a câmera)."""
import pytest

import screen


class FakeClock:
    """Relógio de mentira: sleep() avança o tempo sem esperar de verdade."""

    def __init__(self):
        self.now = 0.0

    def perf_counter(self):
        return self.now

    def sleep(self, sec):
        self.now += max(sec, 0.0)


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(screen, "time", c)
    return c


# ---------------------------------------------------------------- move_to

def test_move_to_ok_quando_o_cursor_chega(monkeypatch):
    monkeypatch.setattr(screen, "on_monitor", lambda x, y: True)
    monkeypatch.setattr(screen, "_move_event", lambda x, y: None)
    monkeypatch.setattr(screen, "cursor_pos", lambda: (10, 20))
    result = screen.move_to(10, 20)
    assert result.ok and result.reason == "ok" and result.pos == (10, 20)


def test_move_to_fora_do_monitor_nao_manda_nenhum_movimento(monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "on_monitor", lambda x, y: False)
    monkeypatch.setattr(screen, "_move_event", lambda x, y: calls.append((x, y)))
    monkeypatch.setattr(screen, "cursor_pos", lambda: (999, 999))
    result = screen.move_to(5000, 5000)
    assert not result.ok
    assert result.reason == "fora_do_monitor"
    assert result.pos == (999, 999)
    assert calls == []  # o ponto nem está numa tela: não vale a pena tentar mover


def test_move_to_usa_desvio_negativo_quando_o_positivo_sai_do_monitor(monkeypatch):
    events = []

    def fake_on_monitor(x, y):
        return not (x == 13 and y == 13)  # só (10+3, 10+3) está fora do monitor

    monkeypatch.setattr(screen, "on_monitor", fake_on_monitor)
    monkeypatch.setattr(screen, "_move_event", lambda x, y: events.append((x, y)))
    monkeypatch.setattr(screen, "cursor_pos", lambda: (10, 10))
    screen.move_to(10, 10)
    assert events[0] == (10 - screen.NUDGE_PX, 10 - screen.NUDGE_PX)


def test_move_to_mexendo_quando_o_cursor_muda_sozinho_no_fim(monkeypatch):
    monkeypatch.setattr(screen, "on_monitor", lambda x, y: True)
    monkeypatch.setattr(screen, "_move_event", lambda x, y: None)
    monkeypatch.setattr(screen, "time", FakeClock())
    # todas as tentativas leem a mesma posição errada; a leitura extra final muda sozinha
    positions = [(999, 999)] * screen.MOVE_TRIES + [(1050, 1050)]
    monkeypatch.setattr(screen, "cursor_pos", lambda: positions.pop(0))
    monkeypatch.setattr(screen.user32, "SetCursorPos", lambda x, y: None)
    result = screen.move_to(10, 10)
    assert not result.ok
    assert result.reason == "mexendo"
    assert result.pos == (1050, 1050)


def test_move_to_preso_quando_o_cursor_fica_parado_fora_do_alvo(monkeypatch):
    monkeypatch.setattr(screen, "on_monitor", lambda x, y: True)
    monkeypatch.setattr(screen, "_move_event", lambda x, y: None)
    monkeypatch.setattr(screen, "time", FakeClock())
    monkeypatch.setattr(screen.user32, "SetCursorPos", lambda x, y: None)
    monkeypatch.setattr(screen, "cursor_pos", lambda: (999, 999))
    result = screen.move_to(10, 10)
    assert not result.ok
    assert result.reason == "preso"
    assert result.pos == (999, 999)


# ---------------------------------------------------------------- click_at

def test_click_at_nao_clica_quando_nao_chega(monkeypatch):
    mouse_calls = []
    monkeypatch.setattr(screen, "move_to", lambda x, y: screen.MoveResult(False, "preso", (1, 2)))
    monkeypatch.setattr(screen, "_mouse", lambda *a, **kw: mouse_calls.append(a))
    result = screen.click_at(10, 10)
    assert not result.ok
    assert mouse_calls == []


def test_click_at_clica_quando_chega(monkeypatch):
    mouse_calls = []
    monkeypatch.setattr(screen, "move_to", lambda x, y: screen.MoveResult(True, "ok", (x, y)))
    monkeypatch.setattr(screen, "_mouse", lambda flags, *a, **kw: mouse_calls.append(flags))
    result = screen.click_at(10, 10)
    assert result.ok
    assert mouse_calls == [screen.MOUSEEVENTF_LEFTDOWN, screen.MOUSEEVENTF_LEFTUP]


def test_move_result_e_avaliavel_como_bool_para_quem_so_quer_isso():
    assert bool(screen.MoveResult(True, "ok", (0, 0))) is True
    assert bool(screen.MoveResult(False, "preso", (0, 0))) is False


# ---------------------------------------------------------------- on_monitor / buttons_held

def test_on_monitor_usa_monitorfrompoint(monkeypatch):
    monkeypatch.setattr(screen.user32, "MonitorFromPoint", lambda pt, flags: 123)
    assert screen.on_monitor(10, 10) is True
    monkeypatch.setattr(screen.user32, "MonitorFromPoint", lambda pt, flags: None)
    assert screen.on_monitor(10, 10) is False


def test_buttons_held_confere_os_dois_botoes(monkeypatch):
    states = {screen.VK_LBUTTON: 0, screen.VK_RBUTTON: 0}
    monkeypatch.setattr(screen.user32, "GetAsyncKeyState", lambda vk: states[vk])
    assert screen.buttons_held() is False
    states[screen.VK_RBUTTON] = -32768  # bit alto ligado = botão apertado
    assert screen.buttons_held() is True


# ---------------------------------------------------------------- wait_mouse_free

def test_wait_mouse_free_true_quando_o_mouse_para_e_solta(monkeypatch, clock):
    positions = [(0, 0), (1, 1), (2, 2)]
    monkeypatch.setattr(screen, "cursor_pos", lambda: positions.pop(0) if positions else (2, 2))
    monkeypatch.setattr(screen, "buttons_held", lambda: False)
    assert screen.wait_mouse_free(timeout=5.0, sleep=clock.sleep) is True


def test_wait_mouse_free_false_quando_o_botao_nao_solta(monkeypatch, clock):
    monkeypatch.setattr(screen, "cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(screen, "buttons_held", lambda: True)
    assert screen.wait_mouse_free(timeout=0.5, sleep=clock.sleep) is False


def test_wait_mouse_free_false_quando_o_cursor_nunca_para(monkeypatch, clock):
    counter = {"x": 0}

    def moving_pos():
        counter["x"] += 1
        return (counter["x"], counter["x"])

    monkeypatch.setattr(screen, "cursor_pos", moving_pos)
    monkeypatch.setattr(screen, "buttons_held", lambda: False)
    assert screen.wait_mouse_free(timeout=0.5, sleep=clock.sleep) is False


# ---------------------------------------------------------------- anti_idle_nudge

def test_anti_idle_nudge_manda_so_movimento_relativo_sem_botao(monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "_mouse", lambda flags, dx=0, dy=0: calls.append((flags, dx, dy)))
    screen.anti_idle_nudge()
    # só MOUSEEVENTF_MOVE (sem ABSOLUTE nem botão nenhum): não pode girar a câmera
    assert all(flags == screen.MOUSEEVENTF_MOVE for flags, _, _ in calls)
    # vai 1px e volta: efeito líquido zero
    assert sum(dx for _, dx, _ in calls) == 0
    assert calls  # mandou pelo menos alguma coisa


# ---------------------------------------------------------------- botão direito / right_drag

def test_release_right_button_manda_rightup_mesmo_se_ja_solto(monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "_mouse", lambda flags, dx=0, dy=0: calls.append(flags))
    screen.release_right_button()
    assert calls == [screen.MOUSEEVENTF_RIGHTUP]


def test_right_drag_segura_arrasta_em_pedacos_e_solta(monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "_mouse", lambda flags, dx=0, dy=0: calls.append((flags, dx)))
    monkeypatch.setattr(screen, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    screen.right_drag(100)
    assert calls[0][0] == screen.MOUSEEVENTF_RIGHTDOWN
    assert calls[-1][0] == screen.MOUSEEVENTF_RIGHTUP
    moves = [dx for flags, dx in calls if flags == screen.MOUSEEVENTF_MOVE]
    assert moves and sum(moves) == 100
    assert all(abs(m) <= screen.RIGHT_DRAG_STEP_PX for m in moves)  # em pedaços, não de uma vez


def test_right_drag_arrasto_negativo_tambem_funciona(monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "_mouse", lambda flags, dx=0, dy=0: calls.append((flags, dx)))
    monkeypatch.setattr(screen, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    screen.right_drag(-90)
    moves = [dx for flags, dx in calls if flags == screen.MOUSEEVENTF_MOVE]
    assert sum(moves) == -90


def test_right_drag_solta_o_botao_mesmo_se_o_movimento_falhar(monkeypatch):
    calls = []

    def fake_mouse(flags, dx=0, dy=0):
        calls.append(flags)
        if flags == screen.MOUSEEVENTF_MOVE:
            raise RuntimeError("falha simulada no meio do arrasto")

    monkeypatch.setattr(screen, "_mouse", fake_mouse)
    monkeypatch.setattr(screen, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    with pytest.raises(RuntimeError):
        screen.right_drag(50)
    assert calls[0] == screen.MOUSEEVENTF_RIGHTDOWN
    assert calls[-1] == screen.MOUSEEVENTF_RIGHTUP  # nunca fica preso, mesmo com exceção
