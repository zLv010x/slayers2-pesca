"""Ponte entre a pesca e o auto relog: quando o jogo cai, reconecta sozinho ou para de vez."""
import copy
from types import SimpleNamespace

import pytest

import config
import relog
import relog_bridge
from window import Rect
from restart_policy import RestartPolicy

MENU = relog.Screen(kind="main_menu", play_pos=(10, 10))
DISC = relog.Screen(kind="disconnected", error_code=278, message="idle 20 minutes",
                    reconnect_pos=(50, 60), leave_pos=(30, 60))
READY = dict(enabled=True, has_spawn_gamepass=True, spawn_set=True, server_mode="vip")


def _cfg(**relog_over):
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["discord"]["notify_problems"] = True
    cfg["relog"].update(relog_over)
    return cfg


@pytest.fixture
def fisher(monkeypatch):
    monkeypatch.setattr(relog_bridge.logbook, "save_evidence", lambda img, reason: None)
    sent = []
    return SimpleNamespace(cfg=_cfg(), stop_for_good=False, recoveries=3, sent=sent,
                           relog_budget=RestartPolicy(),
                           _notify=lambda text, ping=True: sent.append((text, ping)))


def _screen(monkeypatch, screen):
    monkeypatch.setattr(relog_bridge, "lost_game_screen", lambda img, cfg=None: screen)


def _relogger(monkeypatch, result):
    runs = []

    class FakeRelogger:
        def __init__(self, cfg, actions):
            runs.append(cfg)

        def run(self):
            return result
    monkeypatch.setattr(relog_bridge.relog, "Relogger", FakeRelogger)
    return runs


def test_jogo_normal_nao_faz_nada(fisher, monkeypatch):
    _screen(monkeypatch, None)
    assert relog_bridge.handle(fisher, object()) is False
    assert fisher.sent == [] and not fisher.stop_for_good


def test_menu_sem_auto_relog_para_de_vez_e_avisa(fisher, monkeypatch):
    _screen(monkeypatch, MENU)
    with pytest.raises(relog_bridge.StopRun):
        relog_bridge.handle(fisher, object())
    assert fisher.stop_for_good
    assert len(fisher.sent) == 1 and "menu principal" in fisher.sent[0][0] and fisher.sent[0][1] is True


def test_pronto_reconecta_sozinho_e_volta_a_pescar(fisher, monkeypatch):
    fisher.cfg = _cfg(**READY)
    _screen(monkeypatch, DISC)
    runs = _relogger(monkeypatch, relog.RelogResult(True, "ok"))
    assert relog_bridge.handle(fisher, object()) is True
    assert len(runs) == 1 and fisher.recoveries == 0 and not fisher.stop_for_good
    texts = " ".join(t for t, _ in fisher.sent)
    assert "278" in texts and "Reconectado" in texts


def test_codigo_264_nunca_reconecta(fisher, monkeypatch):
    fisher.cfg = _cfg(**READY)
    _screen(monkeypatch, relog.Screen(kind="disconnected", error_code=264, reconnect_pos=(1, 1)))
    runs = _relogger(monkeypatch, relog.RelogResult(True, "ok"))
    with pytest.raises(relog_bridge.StopRun):
        relog_bridge.handle(fisher, object())
    assert runs == [] and fisher.stop_for_good


def test_reconexao_que_falha_para_sem_ser_de_vez(fisher, monkeypatch):
    """Falhou (jogo lento, servidor cheio): o reinício automático tenta de novo mais tarde."""
    fisher.cfg = _cfg(**READY)
    _screen(monkeypatch, MENU)
    _relogger(monkeypatch, relog.RelogResult(False, "timeout_etapa"))
    with pytest.raises(relog_bridge.StopRun):
        relog_bridge.handle(fisher, object())
    assert not fisher.stop_for_good
    assert any("timeout_etapa" in t for t, _ in fisher.sent)


def test_limite_de_reconexoes_por_hora(fisher, monkeypatch):
    fisher.cfg = _cfg(**READY, max_per_hour=2)
    _screen(monkeypatch, MENU)
    runs = _relogger(monkeypatch, relog.RelogResult(True, "ok"))
    assert relog_bridge.handle(fisher, object()) and relog_bridge.handle(fisher, object())
    with pytest.raises(relog_bridge.StopRun):
        relog_bridge.handle(fisher, object())
    assert len(runs) == 2 and fisher.stop_for_good


@pytest.mark.parametrize("over, reason", [
    ({}, "desligado"),
    (dict(enabled=True), "gamepass"),
    (dict(enabled=True, has_spawn_gamepass=True), "spawn"),
    (dict(READY, server_mode="nick", owner_nick=" "), "nick"),
])
def test_motivo_de_nao_estar_pronto(over, reason):
    assert reason in relog_bridge.not_ready_reason(_cfg(**over))


def test_pronto_sem_motivo():
    assert relog_bridge.not_ready_reason(_cfg(**READY)) is None
    assert relog_bridge.not_ready_reason(_cfg(**dict(READY, server_mode="nick", owner_nick="Lv_010"))) is None


def test_dialog_sem_botao_nao_conta_como_queda(monkeypatch):
    """Alguém escrevendo "disconnected" no chat não pode parar a pesca."""
    monkeypatch.setattr(relog_bridge.relog, "classify",
                        lambda img, cfg=None: relog.Screen(kind="disconnected", message="lol disconnected"))
    assert relog_bridge.lost_game_screen(object()) is None


def test_so_menu_e_desconectado_disparam(monkeypatch):
    for kind in ("server_select", "server_card", "loading", "unknown"):
        monkeypatch.setattr(relog_bridge.relog, "classify", lambda img, cfg=None, k=kind: relog.Screen(kind=k))
        assert relog_bridge.lost_game_screen(object()) is None


def test_acoes_somam_a_origem_da_janela(monkeypatch):
    clicks = []
    monkeypatch.setattr(relog_bridge.screen, "click_at", lambda x, y: clicks.append((x, y)))
    frame = object()
    f = SimpleNamespace(rect=lambda: Rect(100, 50, 800, 600),
                        grabber=SimpleNamespace(grab=lambda r: frame))
    actions = relog_bridge.RelogActions(f)
    assert actions.grab() == (100, 50, frame)
    actions.click(10, 20)
    assert clicks == [(110, 70)]


def test_set_spawn_usa_as_acoes_da_pesca(monkeypatch):
    seen = []

    class FakeSetter:
        def __init__(self, actions):
            seen.append(type(actions).__name__)

        def run(self):
            return relog_bridge.spawn.SpawnResult(True, "ok")
    monkeypatch.setattr(relog_bridge.spawn, "Setter", FakeSetter)
    assert relog_bridge.set_spawn(SimpleNamespace()).ok
    assert seen == ["RelogActions"]


def test_erro_no_meio_do_spawn_fecha_a_caixinha_e_devolve_falha(monkeypatch):
    clicks = []

    class Boom:
        def __init__(self, actions):
            pass

        def run(self):
            raise RuntimeError("ocr quebrou")
    monkeypatch.setattr(relog_bridge.spawn, "Setter", Boom)
    monkeypatch.setattr(relog_bridge.spawn, "classify",
                        lambda frame: relog_bridge.spawn.SpawnScreen("closed_box", cancel_pos=(5, 6)))
    monkeypatch.setattr(relog_bridge.screen, "click_at", lambda x, y: clicks.append((x, y)) or True)
    f = SimpleNamespace(rect=lambda: Rect(100, 50, 800, 600), grabber=SimpleNamespace(grab=lambda r: "img"))
    result = relog_bridge.set_spawn(f)
    assert not result.ok and "RuntimeError" in result.reason
    assert clicks == [(105, 56)]


def test_segurar_join_sem_o_cursor_chegar_nao_aperta(monkeypatch):
    pressed = []
    monkeypatch.setattr(relog_bridge.screen, "move_to", lambda x, y: False)
    f = SimpleNamespace(mouse=SimpleNamespace(set=lambda on: pressed.append(on)))
    assert relog_bridge.RelogActions(f).mouse_down(10, 10) is False
    assert pressed == []
