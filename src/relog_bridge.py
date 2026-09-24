"""Liga o auto relog (relog.py) à pesca.

Quando o jogo cai (menu principal ou dialog "Disconnected"), a pesca chama `handle`:
- relog pronto (ligado, com o gamepass de spawn e o spawn setado no ponto de pesca):
  reconecta sozinho e a pesca recomeça o ciclo;
- não pronto, código que não reconecta (264 = conta em outro PC) ou reconexões demais
  numa hora: para de vez e avisa (reiniciar sozinho não adiantaria);
- a reconexão falhou (jogo lento, servidor cheio): para, mas sem ser "de vez", e o
  reinício automático do app tenta de novo mais tarde.
"""
from __future__ import annotations

import time

import numpy as np

import logbook
import relog
import screen
from stops import StopRun

log = logbook.get()
# Só essas telas disparam: as outras (servidor, carregando) só aparecem no meio do relog.
ENTRY_KINDS = ("disconnected", "main_menu")
DEFAULT_MAX_PER_HOUR = 4


class RelogActions:
    """Mouse, teclado e tela que o Relogger pede, em cima da pesca (Fisher).

    O Relogger trabalha em pixels do print; aqui soma a origem da janela do Roblox.
    """

    def __init__(self, fisher) -> None:
        self.f = fisher
        self._origin = (0, 0)

    def grab(self):
        r = self.f.rect()
        self._origin = (r.x, r.y)
        return r.x, r.y, self.f.grabber.grab(r)

    def _abs(self, x: int, y: int) -> tuple[int, int]:
        return self._origin[0] + int(x), self._origin[1] + int(y)

    def click(self, x: int, y: int) -> None:
        screen.click_at(*self._abs(x, y))

    def mouse_down(self, x: int, y: int) -> None:
        screen.move_to(*self._abs(x, y))
        self.f.mouse.set(True)

    def mouse_up(self) -> None:
        self.f.mouse.release()

    def type_text(self, text: str) -> None:
        screen.type_text(text)

    def press(self, key: str) -> None:
        screen.tap_key(key)

    def sleep(self, sec: float) -> None:
        self.f.sleep(sec)

    def now(self) -> float:
        return time.perf_counter()

    def in_game(self, frame: np.ndarray) -> bool:
        return False  # o Relogger confirma a volta pela tela "desconhecida" por alguns segundos

    def status(self, msg: str) -> None:
        self.f.cb.status(msg)


def not_ready_reason(cfg: dict) -> str | None:
    """Por que o auto relog não pode rodar (None = pode)."""
    r = cfg.get("relog", {})
    if not r.get("enabled"):
        return "auto relog desligado"
    if not r.get("has_spawn_gamepass"):
        return "precisa do gamepass de spawn"
    if not r.get("spawn_set"):
        return "o spawn não foi setado no ponto de pesca"
    if r.get("server_mode") == "nick" and not str(r.get("owner_nick", "")).strip():
        return "falta o nick do dono do servidor"
    return None


def lost_game_screen(img: np.ndarray | None, cfg: dict | None = None) -> relog.Screen | None:
    """Menu principal ou dialog "Disconnected" de verdade (com botão) na tela?"""
    s = relog.classify(img, cfg)
    if s.kind == "main_menu":
        return s
    if s.kind == "disconnected" and (s.reconnect_pos or s.leave_pos):
        return s  # sem botão é texto solto (ex.: alguém escreveu "disconnected" no chat)
    return None


def _describe(s: relog.Screen) -> str:
    if s.kind == "main_menu":
        return "o jogo voltou para o menu principal (o servidor reiniciou ou você caiu)"
    code = f" (código {s.error_code})" if s.error_code is not None else ""
    msg = f": {s.message}" if s.message else ""
    return f"desconectado do jogo{code}{msg}"


def _stop_for_good(f, msg: str) -> None:
    key = f.cfg["hotkeys"]["start_stop"]
    full = f"{msg}. Entre de novo, volte ao ponto de pesca e aperte {key}."
    log.error("Pesca parada de vez: %s", full)
    f._notify("🏠 Pesca parada: " + full)
    f.stop_for_good = True
    raise StopRun("Parei: " + full)


def handle(f, img: np.ndarray | None) -> bool:
    """O jogo caiu? True = reconectou sozinho; False = nada caiu. Senão levanta StopRun."""
    try:
        s = lost_game_screen(img, f.cfg.get("relog"))
    except Exception:  # OCR falhou: segue como um problema comum
        log.exception("Não consegui conferir se o jogo caiu")
        return False
    if s is None:
        return False
    what = _describe(s)
    logbook.save_evidence(img, "caiu do jogo")
    r = f.cfg.get("relog", {})
    if s.kind == "disconnected" and s.error_code in r.get("no_reconnect_codes", [264]):
        _stop_for_good(f, f"{what}; esse código não reconecta sozinho")
    reason = not_ready_reason(f.cfg)
    if reason:
        _stop_for_good(f, f"{what} (auto relog: {reason})")
    if not f.relog_budget.allowed(int(r.get("max_per_hour", DEFAULT_MAX_PER_HOUR))):
        _stop_for_good(f, f"{what}, e já reconectei demais na última hora")
    return _reconnect(f, what)


def _reconnect(f, what: str) -> bool:
    f.relog_budget.record_restart()
    log.warning("Caiu do jogo: %s. Reconectando sozinho.", what)
    f._notify(f"🔁 {what}: reconectando sozinho...", ping=False)
    result = relog.Relogger(f.cfg["relog"], RelogActions(f)).run()
    if result.ok:
        log.info("Reconectado: voltando a pescar.")
        f._notify("✅ Reconectado: voltando a pescar.", ping=False)
        f.recoveries = 0
        return True
    if result.reason == "codigo_sem_reconexao":
        _stop_for_good(f, f"{what}; esse código não reconecta sozinho")
    msg = f"não consegui reconectar sozinho ({result.reason})"
    log.error(msg)
    f._notify(f"🛑 {msg}. Tento de novo no próximo reinício automático.")
    raise StopRun("Parei: " + msg)
