"""Reinício automático e fechar a macro, sem abrir a janela (objeto falso no lugar do App)."""
import threading
from types import SimpleNamespace

import app


class FakePolicy:
    def __init__(self):
        self.recorded = 0

    def record_restart(self):
        self.recorded += 1


def _fake(**over):
    sent, scheduled = [], []
    fake = SimpleNamespace(
        _restart_job=None, _running=False, _listening=None, _picker_open=False,
        _restart_policy=FakePolicy(), sent=sent, scheduled=scheduled,
        _notify_problem=sent.append,
        after=lambda ms, fn: scheduled.append((ms, fn)) or "job",
        status=SimpleNamespace(cget=lambda key: "Marque o ponto de lançamento antes de começar."),
    )
    fake.calls = []
    fake.toggle_run = lambda **kw: fake.calls.append(kw) or setattr(fake, "_running", True)
    fake._auto_restart = lambda: app.App._auto_restart(fake)
    for key, value in over.items():
        setattr(fake, key, value)
    return fake


def test_reinicio_com_marcador_aberto_tenta_depois_sem_gastar_a_vez():
    """Revisão de 24/09: antes avisava "reiniciando" no Discord e não reiniciava."""
    fake = _fake(_picker_open=True)
    app.App._auto_restart(fake)
    assert fake._running is False
    assert fake.sent == [] and fake._restart_policy.recorded == 0
    assert fake.scheduled and fake._restart_job == "job"


def test_reinicio_normal_conta_e_avisa():
    fake = _fake()
    app.App._auto_restart(fake)
    assert fake._running is True
    assert fake.calls == [{"by_user": False}]  # reinício sozinho nunca seta o spawn
    assert fake._restart_policy.recorded == 1
    assert any("Reiniciando" in m for m in fake.sent)


def test_reinicio_que_nao_consegue_iniciar_avisa_o_motivo():
    fake = _fake()
    fake.toggle_run = lambda **kw: None  # ex.: ponto de lançamento apagado
    app.App._auto_restart(fake)
    assert fake._restart_policy.recorded == 0
    assert len(fake.sent) == 1 and "Marque o ponto" in fake.sent[0]


class StuckWorker:
    def join(self, timeout=None):
        pass

    def is_alive(self):
        return True


def test_fechar_com_a_pesca_travada_solta_t_e_mouse(monkeypatch):
    released = []
    monkeypatch.setattr(app.screen, "release_key", lambda k: released.append(k))
    monkeypatch.setattr(app.screen.MouseButton, "release", lambda self: released.append("mouse"))
    monkeypatch.setattr(app.keyboard, "unhook_all_hotkeys", lambda: None)
    fake = SimpleNamespace(_worker=StuckWorker(), _stop=threading.Event(),
                           _cancel_auto_restart=lambda: None, _save_now=lambda: None, destroy=lambda: None,
                           pulse=SimpleNamespace(close=lambda: None))
    app.App.close(fake)
    assert fake._stop.is_set()
    assert released == ["t", "mouse"]
