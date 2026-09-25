"""Cão de guarda: reabre a macro se ela travar pescando.

Noite de 24/09: a macro travou 2x no PC do usuário e 1x no do Ewerton, sempre logo depois de
pegar um item, e ficou parada até de manhã (processo congelado, sem erro no log). Dois lados:

- Pulse (dentro da macro): a pesca "bate" a cada volta (_check_stop). A cada `every` segundos
  grava logs/pulso.json {"pid", "fishing", "closed", "t"} e rearma o faulthandler, que grava
  em logs/travamento.txt onde cada thread está parada se ficar DUMP_AFTER_SEC sem bater
  (para achar a causa do travamento).
- este arquivo como processo separado (`python src/watchdog.py <pid>`): se a macro estiver
  pescando e ficar HANG_SEC sem pulso (ou morrer pescando), fecha a macro, abre de novo com
  --retomar e sai (a macro nova abre outro cão de guarda). No máximo MAX_RESTARTS_PER_HOUR.
"""
from __future__ import annotations

import ctypes
import faulthandler
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

PULSE_EVERY_SEC = 10.0
DUMP_AFTER_SEC = 180.0       # sem pulso por 3 min: grava onde cada thread está (diagnóstico)
HANG_SEC = 300.0             # sem pulso por 5 min pescando: é travamento
CHECK_EVERY_SEC = 20.0
MAX_RESTARTS_PER_HOUR = 3
RESUME_FLAG = "--retomar"
PULSE_NAME = "pulso.json"
BUDGET_NAME = "reinicios-cao-de-guarda.json"
DUMP_NAME = "travamento.txt"
LOG_NAME = "cao-de-guarda.log"
HOUR_SEC = 3600.0

# Windows: processo sem janela nem console, desligado da macro (sobrevive a ela)
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_TIMEOUT = 0x102


def wants_resume(argv: list[str]) -> bool:
    return RESUME_FLAG in argv[1:]


# ---------------------------------------------------------------- pulso (dentro da macro)
def write_pulse(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def read_pulse(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Pulse:
    """Sinal de vida da macro para o cão de guarda (thread-safe; beat() é barato)."""

    def __init__(self, path: Path, pid: int, every: float = PULSE_EVERY_SEC,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 dump_path: Path | None = None, dump_after: float = DUMP_AFTER_SEC) -> None:
        self.path, self.pid, self.every = Path(path), pid, every
        self._clock, self._wall = clock, wall
        self._lock = threading.Lock()
        self._fishing = False
        self._last = float("-inf")
        self._dump_after = dump_after
        self._dump_file = None
        if dump_path is not None:
            try:
                self._dump_file = open(dump_path, "a", encoding="utf-8")  # aberto: o faulthandler usa o fd
            except OSError:
                self._dump_file = None

    def beat(self) -> None:
        """Chamado pela pesca a cada volta; grava no máximo a cada `every` segundos."""
        if not self._fishing or self._clock() - self._last < self.every:
            return
        with self._lock:
            if self._fishing and self._clock() - self._last >= self.every:
                self._write()
                self._arm_dump()

    def set_fishing(self, on: bool) -> None:
        with self._lock:
            self._fishing = on
            self._write()
            if on:
                self._arm_dump()
            else:
                self._cancel_dump()

    def close(self) -> None:
        with self._lock:
            self._fishing = False
            self._write(closed=True)
            self._cancel_dump()

    def _write(self, closed: bool = False) -> None:
        self._last = self._clock()
        try:
            write_pulse(self.path, {"pid": self.pid, "fishing": self._fishing, "closed": closed,
                                    "t": self._wall()})
        except OSError:
            pass  # disco travado: o cão de guarda só vê um pulso mais velho

    def _arm_dump(self) -> None:
        if self._dump_file is None:
            return
        try:
            self._dump_file.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} rearmado ====\n")
            self._dump_file.flush()
            faulthandler.dump_traceback_later(self._dump_after, repeat=False, file=self._dump_file)
        except (OSError, ValueError, RuntimeError):
            pass

    def _cancel_dump(self) -> None:
        if self._dump_file is not None:
            faulthandler.cancel_dump_traceback_later()


# ---------------------------------------------------------------- decisão (cão de guarda)
def decide(pulse: dict | None, pid: int, alive: bool, now: float, hang_sec: float = HANG_SEC) -> str:
    """"wait", "restart" ou "exit" para a macro `pid`."""
    if pulse is None or pulse.get("pid") != pid:
        return "wait" if alive else "exit"
    if pulse.get("closed"):
        return "exit"
    if not alive:
        return "restart" if pulse.get("fishing") else "exit"
    if pulse.get("fishing") and now - float(pulse.get("t", now)) > hang_sec:
        return "restart"
    return "wait"


class RestartBudget:
    """Reinícios do cão de guarda na última hora (guardado em disco: sobrevive às macros)."""

    def __init__(self, path: Path, max_per_hour: int = MAX_RESTARTS_PER_HOUR) -> None:
        self.path, self.max_per_hour = Path(path), max_per_hour

    def _times(self, now: float) -> list[float]:
        try:
            times = [float(t) for t in json.loads(self.path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            times = []
        return [t for t in times if now - t < HOUR_SEC]

    def allowed(self, now: float) -> bool:
        return len(self._times(now)) < self.max_per_hour

    def record(self, now: float) -> None:
        try:
            self.path.write_text(json.dumps(self._times(now) + [now]), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------- processo (Windows)
def is_alive(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def kill(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        ok = bool(kernel32.TerminateProcess(handle, 1))
        kernel32.WaitForSingleObject(handle, 10_000)
        return ok
    finally:
        kernel32.CloseHandle(handle)


def spawn(args: list[str], cwd: Path) -> None:
    subprocess.Popen(args, cwd=str(cwd), close_fds=True, creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)


def start_guard(pid: int) -> None:
    """Abre o cão de guarda desta macro (processo separado, sem janela)."""
    root = Path(__file__).resolve().parent.parent
    spawn([sys.executable, str(Path(__file__).resolve()), str(pid)], root)


def run(pid: int, root: Path, check_every: float = CHECK_EVERY_SEC, hang_sec: float = HANG_SEC,
        relaunch: list[str] | None = None) -> str:
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    log = logging.getLogger("cao-de-guarda")
    budget = RestartBudget(logs / BUDGET_NAME)
    log.info("Vigiando a macro (pid %d).", pid)
    while True:
        time.sleep(check_every)
        action = decide(read_pulse(logs / PULSE_NAME), pid, is_alive(pid), time.time(), hang_sec)
        if action == "wait":
            continue
        if action == "exit":
            log.info("Macro fechada: cão de guarda saindo.")
            return action
        if not budget.allowed(time.time()):
            log.error("A macro travou de novo, mas já reabri %d vezes na última hora: desisto.",
                      MAX_RESTARTS_PER_HOUR)
            return "exit"
        log.error("A macro parou de responder pescando: fechando (pid %d) e abrindo de novo.", pid)
        budget.record(time.time())
        kill(pid)
        spawn(relaunch or [sys.executable, str(root / "src" / "app.py"), RESUME_FLAG], root)
        return action


def main(argv: list[str]) -> None:
    root = Path(__file__).resolve().parent.parent
    (root / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=str(root / "logs" / LOG_NAME), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)-7s %(message)s")
    try:
        run(int(argv[1]), root)
    except Exception:  # o cão de guarda nunca pode quebrar sem deixar rastro
        logging.getLogger("cao-de-guarda").exception("Cão de guarda caiu")


if __name__ == "__main__":
    main(sys.argv)
