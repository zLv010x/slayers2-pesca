"""Sensibilidade da câmera no app: gatilho (a) botão em Configurar e a fiação com
camera_cal.py, sem abrir janela de verdade (objeto falso no lugar do App, como em
test_app_restart.py). Nada aqui mexe no mouse de verdade: right_drag/move_to/Grabber
são todos substituídos."""
import time
from types import SimpleNamespace

import pytest

import app


def _setup_tab():
    calls = []
    return SimpleNamespace(set_camera_cal_status=calls.append), calls


# ---------------------------------------------------------------- test_camera_sensitivity

def test_recusa_com_a_pesca_rodando():
    setup_tab, calls = _setup_tab()
    statuses = []
    fake = SimpleNamespace(_running=True, _picker_open=False, _camera_cal_running=False,
                           set_status=statuses.append, setup_tab=setup_tab,
                           cfg={"cast_point": {"x": 0.5, "y": 0.5}}, compass=SimpleNamespace(ready=True))
    app.App.test_camera_sensitivity(fake)
    assert statuses and "testar a câmera" in statuses[0]
    assert calls == []


def test_recusa_ja_testando():
    setup_tab, calls = _setup_tab()
    statuses = []
    fake = SimpleNamespace(_running=False, _picker_open=False, _camera_cal_running=True,
                           set_status=statuses.append, setup_tab=setup_tab,
                           cfg={"cast_point": {"x": 0.5, "y": 0.5}}, compass=SimpleNamespace(ready=True))
    app.App.test_camera_sensitivity(fake)
    assert statuses and "testar a câmera" in statuses[0]


def test_recusa_sem_ponto_marcado():
    setup_tab, calls = _setup_tab()
    fake = SimpleNamespace(_running=False, _picker_open=False, _camera_cal_running=False,
                           set_status=lambda t: None, setup_tab=setup_tab,
                           cfg={"cast_point": None}, compass=SimpleNamespace(ready=False))
    app.App.test_camera_sensitivity(fake)
    assert calls and "Marque o ponto" in calls[0]


def test_recusa_sem_bussola_marcada():
    """Ponto marcado mas a bússola não (ex.: config.json editado à mão)."""
    setup_tab, calls = _setup_tab()
    fake = SimpleNamespace(_running=False, _picker_open=False, _camera_cal_running=False,
                           set_status=lambda t: None, setup_tab=setup_tab,
                           cfg={"cast_point": {"x": 0.5, "y": 0.5}}, compass=SimpleNamespace(ready=False))
    app.App.test_camera_sensitivity(fake)
    assert calls and "Marque o ponto" in calls[0]


def test_inicia_a_calibracao_numa_thread(monkeypatch):
    setup_tab, calls = _setup_tab()
    monkeypatch.setattr(app.window, "find_roblox", lambda: 123)
    monkeypatch.setattr(app.window, "focus", lambda hwnd: True)
    started, done = [], __import__("threading").Event()
    fake = SimpleNamespace(
        _running=False, _picker_open=False, _camera_cal_running=False,
        set_status=lambda t: None, setup_tab=setup_tab, cfg={"cast_point": {"x": 0.5, "y": 0.5}},
        compass=SimpleNamespace(ready=True), _game_rect=lambda: object(),
        _run_camera_cal=lambda hwnd: (started.append(hwnd), done.set()))
    fake._start_camera_cal = lambda: app.App._start_camera_cal(fake)
    app.App.test_camera_sensitivity(fake)
    assert done.wait(timeout=2), "a thread da calibração não rodou"
    assert started == [123]
    assert fake._camera_cal_running is True
    assert calls and "Testando" in calls[-1]


# ---------------------------------------------------------------- _start_camera_cal

def test_start_camera_cal_nao_faz_nada_ja_rodando():
    setup_tab, calls = _setup_tab()
    fake = SimpleNamespace(_camera_cal_running=True, cfg={"cast_point": {"x": 0.5, "y": 0.5}},
                           compass=SimpleNamespace(ready=True), setup_tab=setup_tab)
    app.App._start_camera_cal(fake)
    assert calls == []  # não reiniciou nem mudou o status


def test_start_camera_cal_traz_o_roblox_para_frente(monkeypatch):
    """Gatilho (b): `_restore_window` acabou de trazer a própria macro para cima depois do
    picker fechar; o teste precisa focar o Roblox de novo antes de mexer no botão direito."""
    setup_tab, calls = _setup_tab()
    monkeypatch.setattr(app.window, "find_roblox", lambda: 55)
    focused = []
    monkeypatch.setattr(app.window, "focus", lambda hwnd: focused.append(hwnd))
    fake = SimpleNamespace(_camera_cal_running=False, cfg={"cast_point": {"x": 0.5, "y": 0.5}},
                           compass=SimpleNamespace(ready=True), setup_tab=setup_tab,
                           _run_camera_cal=lambda hwnd: None)
    app.App._start_camera_cal(fake)
    assert focused == [55]


def test_start_camera_cal_nao_faz_nada_sem_roblox(monkeypatch):
    setup_tab, calls = _setup_tab()
    monkeypatch.setattr(app.window, "find_roblox", lambda: None)
    fake = SimpleNamespace(_camera_cal_running=False, cfg={"cast_point": {"x": 0.5, "y": 0.5}},
                           compass=SimpleNamespace(ready=True), setup_tab=setup_tab)
    app.App._start_camera_cal(fake)
    assert fake._camera_cal_running is False
    assert calls == []


# ---------------------------------------------------------------- _camera_cal_actions

def test_camera_cal_actions_grab_frame_usa_o_rect_atual(monkeypatch):
    grabbed = []
    monkeypatch.setattr(app.window, "client_rect", lambda hwnd: "RECT-42" if hwnd == 42 else None)
    grabber = SimpleNamespace(grab=lambda rect: grabbed.append(rect) or "IMG")
    fake = SimpleNamespace(compass=SimpleNamespace(drift_px=lambda img: 7), post=lambda fn: fn(),
                           setup_tab=SimpleNamespace(set_camera_cal_status=lambda t: None))
    actions = app.App._camera_cal_actions(fake, 42, grabber)
    assert actions.grab_frame() == "IMG"
    assert grabbed == ["RECT-42"]
    assert actions.drift("IMG") == 7


def test_camera_cal_actions_grab_frame_falha_se_janela_sumiu(monkeypatch):
    monkeypatch.setattr(app.window, "client_rect", lambda hwnd: None)
    grabber = SimpleNamespace(grab=lambda rect: pytest.fail("não devia tentar tirar print sem janela"))
    fake = SimpleNamespace(compass=SimpleNamespace(drift_px=lambda img: None), post=lambda fn: fn(),
                           setup_tab=SimpleNamespace(set_camera_cal_status=lambda t: None))
    actions = app.App._camera_cal_actions(fake, 42, grabber)
    with pytest.raises(RuntimeError):
        actions.grab_frame()


def test_camera_cal_actions_status_manda_para_o_setup_tab_via_post():
    posted = []
    shown = []
    fake = SimpleNamespace(compass=SimpleNamespace(drift_px=lambda img: 0),
                           post=lambda fn: posted.append(fn),
                           setup_tab=SimpleNamespace(set_camera_cal_status=shown.append))
    actions = app.App._camera_cal_actions(fake, 42, SimpleNamespace(grab=lambda r: None))
    actions.status("oi")
    assert len(posted) == 1
    posted[0]()  # roda como a interface rodaria
    assert shown == ["oi"]


# ---------------------------------------------------------------- _run_camera_cal

def test_run_camera_cal_solta_o_mouse_e_o_botao_direito_sempre(monkeypatch):
    """O teste mexe no mouse: nunca pode deixar o botão direito preso, mesmo dando erro."""
    monkeypatch.setattr(app.screen, "wait_mouse_free", lambda **kw: True)
    monkeypatch.setattr(app.window, "client_rect", lambda hwnd: (_ for _ in ()).throw(RuntimeError("sumiu")))
    released, closed = [], []
    monkeypatch.setattr(app.screen, "release_right_button", lambda: released.append(True))
    monkeypatch.setattr(app.screen, "Grabber", lambda: SimpleNamespace(
        grab=lambda rect: "IMG", close=lambda: closed.append(True)))
    posted = []
    fake = SimpleNamespace(cfg={"cast_point": None}, compass=SimpleNamespace(drift_px=lambda img: 0, ready=True),
                           post=posted.append, setup_tab=SimpleNamespace(set_camera_cal_status=lambda t: None))
    app.App._run_camera_cal(fake, hwnd=42)
    assert released == [True]
    assert closed == [True]
    assert len(posted) == 1  # sempre avisa o resultado, mesmo com erro


def test_run_camera_cal_sucesso_poe_o_cursor_no_ponto_e_mede(monkeypatch):
    monkeypatch.setattr(app.screen, "wait_mouse_free", lambda **kw: True)
    monkeypatch.setattr(app.window, "client_rect", lambda hwnd: app.window.Rect(0, 0, 100, 100))
    moves = []
    monkeypatch.setattr(app.screen, "move_to", lambda x, y: moves.append((x, y)))
    monkeypatch.setattr(app.screen, "release_right_button", lambda: None)
    monkeypatch.setattr(app.screen, "Grabber", lambda: SimpleNamespace(grab=lambda rect: "IMG", close=lambda: None))
    measured = []

    def fake_measure(actions, **kw):
        measured.append(actions)
        return app.camera_cal.CameraCalResult(True, 16.3, None)

    monkeypatch.setattr(app.camera_cal, "measure_camera_gain", fake_measure)
    posted = []
    fake = SimpleNamespace(cfg={"cast_point": {"x": 0.5, "y": 0.25}},
                           compass=SimpleNamespace(drift_px=lambda img: 0, ready=True),
                           post=posted.append, setup_tab=SimpleNamespace(set_camera_cal_status=lambda t: None))
    fake._camera_cal_actions = lambda hwnd, grabber: app.App._camera_cal_actions(fake, hwnd, grabber)
    app.App._run_camera_cal(fake, hwnd=42)
    assert moves == [(50, 25)]  # cursor foi para o ponto de lançamento antes de medir
    assert len(measured) == 1
    assert len(posted) == 1


# ---------------------------------------------------------------- resultado e persistência

def test_on_camera_cal_done_sucesso_salva_o_ganho():
    statuses, saved = [], []
    fake = SimpleNamespace(_camera_cal_running=True,
                           setup_tab=SimpleNamespace(set_camera_cal_status=statuses.append),
                           _save_camera_gain=saved.append)
    app.App._on_camera_cal_done(fake, app.camera_cal.CameraCalResult(True, 16.3, None))
    assert fake._camera_cal_running is False
    assert saved == [16.3]
    assert statuses and "16.3" in statuses[-1]


def test_on_camera_cal_done_falha_mostra_o_motivo_sem_salvar():
    statuses, saved = [], []
    fake = SimpleNamespace(_camera_cal_running=True,
                           setup_tab=SimpleNamespace(set_camera_cal_status=statuses.append),
                           _save_camera_gain=saved.append)
    app.App._on_camera_cal_done(fake, app.camera_cal.CameraCalResult(False, None, "bússola não encontrada"))
    assert fake._camera_cal_running is False
    assert saved == []
    assert statuses and "bússola não encontrada" in statuses[-1]


def test_on_camera_gain_learned_salva_e_avisa_que_foi_durante_a_pesca():
    statuses, saved = [], []
    fake = SimpleNamespace(setup_tab=SimpleNamespace(set_camera_cal_status=statuses.append),
                           _save_camera_gain=saved.append)
    app.App._on_camera_gain_learned(fake, 12.5)
    assert saved == [12.5]
    assert statuses and "12.5" in statuses[-1] and "pesca" in statuses[-1]


def test_save_camera_gain_grava_no_cfg_com_timestamp_e_agenda_salvar():
    saved_soon = []
    fake = SimpleNamespace(cfg={}, save_soon=lambda: saved_soon.append(True))
    app.App._save_camera_gain(fake, 9.5)
    assert fake.cfg["camera_gain"] == 9.5
    assert fake.cfg["camera_gain_measured_at"]
    assert saved_soon == [True]
