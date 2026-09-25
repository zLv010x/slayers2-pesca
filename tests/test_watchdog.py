"""Cão de guarda: reabre a macro se ela travar pescando (noite de 24/09 perdida 2x no PC do
usuário e 1x no do Ewerton, sempre logo depois de pegar um item)."""
import json

import watchdog

PID = 4242
HANG = 300


def pulse(**over):
    data = {"pid": PID, "fishing": True, "closed": False, "t": 1000.0}
    data.update(over)
    return data


def test_pescando_com_pulso_recente_so_espera():
    assert watchdog.decide(pulse(t=1000.0), PID, alive=True, now=1100.0, hang_sec=HANG) == "wait"


def test_pescando_sem_pulso_ha_muito_tempo_reinicia():
    assert watchdog.decide(pulse(t=1000.0), PID, alive=True, now=1000.0 + HANG + 1, hang_sec=HANG) == "restart"


def test_parado_sem_pulso_nao_reinicia():
    """Macro aberta sem pescar não bate pulso: não é travamento."""
    assert watchdog.decide(pulse(fishing=False), PID, alive=True, now=99999.0, hang_sec=HANG) == "wait"


def test_morreu_pescando_reinicia_e_morreu_parada_sai():
    assert watchdog.decide(pulse(), PID, alive=False, now=1001.0, hang_sec=HANG) == "restart"
    assert watchdog.decide(pulse(fishing=False), PID, alive=False, now=1001.0, hang_sec=HANG) == "exit"


def test_fechou_normal_sai():
    assert watchdog.decide(pulse(closed=True), PID, alive=True, now=1001.0, hang_sec=HANG) == "exit"


def test_pulso_de_outra_macro_nao_e_comigo():
    assert watchdog.decide(pulse(pid=1), PID, alive=True, now=99999.0, hang_sec=HANG) == "wait"
    assert watchdog.decide(None, PID, alive=False, now=1.0, hang_sec=HANG) == "exit"


def test_no_maximo_3_reinicios_por_hora(tmp_path):
    budget = watchdog.RestartBudget(tmp_path / "reinicios.json", max_per_hour=3)
    for t in (0.0, 100.0, 200.0):
        assert budget.allowed(t)
        budget.record(t)
    assert not budget.allowed(300.0)
    assert watchdog.RestartBudget(tmp_path / "reinicios.json", max_per_hour=3).allowed(3601.0)  # guardado


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_pulso_grava_no_maximo_a_cada_10s(tmp_path):
    clock = FakeClock()
    path = tmp_path / "pulso.json"
    p = watchdog.Pulse(path, PID, every=10.0, clock=clock, wall=clock, dump_path=None)
    p.set_fishing(True)
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["fishing"] and first["pid"] == PID
    clock.t = 5.0
    p.beat()
    assert json.loads(path.read_text(encoding="utf-8"))["t"] == first["t"]  # cedo demais: não grava
    clock.t = 11.0
    p.beat()
    assert json.loads(path.read_text(encoding="utf-8"))["t"] == 11.0


def test_parar_e_fechar_gravam_na_hora(tmp_path):
    clock = FakeClock()
    path = tmp_path / "pulso.json"
    p = watchdog.Pulse(path, PID, every=10.0, clock=clock, wall=clock, dump_path=None)
    p.set_fishing(True)
    p.set_fishing(False)
    assert json.loads(path.read_text(encoding="utf-8"))["fishing"] is False
    p.close()
    assert json.loads(path.read_text(encoding="utf-8"))["closed"] is True


def test_pulso_parado_nao_grava_batida(tmp_path):
    """Batida atrasada da pesca depois de parar não pode dizer que voltou a pescar."""
    clock = FakeClock()
    path = tmp_path / "pulso.json"
    p = watchdog.Pulse(path, PID, every=10.0, clock=clock, wall=clock, dump_path=None)
    p.set_fishing(False)
    clock.t = 50.0
    p.beat()
    assert json.loads(path.read_text(encoding="utf-8"))["fishing"] is False


def test_retomar_pela_linha_de_comando():
    assert watchdog.wants_resume(["app.py", "--retomar"]) and not watchdog.wants_resume(["app.py"])


def test_de_verdade_fecha_a_macro_travada_e_abre_outra(tmp_path):
    """Processos reais: um "programa travado" que parou de dar sinal é fechado e reaberto."""
    import subprocess
    import sys
    import time
    hung = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    (tmp_path / "logs").mkdir()
    watchdog.write_pulse(tmp_path / "logs" / watchdog.PULSE_NAME,
                         {"pid": hung.pid, "fishing": True, "closed": False, "t": time.time() - 10})
    marker = tmp_path / "reaberta.txt"
    action = watchdog.run(hung.pid, tmp_path, check_every=0.1, hang_sec=5,
                          relaunch=[sys.executable, "-c", f"open(r'{marker}', 'w').write('ok')"])
    assert action == "restart"
    assert hung.wait(timeout=10) is not None  # o travado foi fechado
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.read_text() == "ok"  # e outro foi aberto no lugar


def test_grava_onde_cada_thread_parou_se_ficar_sem_sinal(tmp_path):
    import time
    dump = tmp_path / "travamento.txt"
    p = watchdog.Pulse(tmp_path / "pulso.json", PID, dump_path=dump, dump_after=0.3)
    p.set_fishing(True)
    time.sleep(0.8)
    p.set_fishing(False)
    text = dump.read_text(encoding="utf-8")
    assert "Thread" in text and "test_watchdog.py" in text
