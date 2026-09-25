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

import capture_mode
import logbook
import window
import relog
import screen
import spawn
from stops import StopRun

log = logbook.get()
# Só essas telas disparam: as outras (servidor, carregando) só aparecem no meio do relog.
ENTRY_KINDS = ("disconnected", "main_menu")
DEFAULT_MAX_PER_HOUR = 4
SPAWN_NOT_SET = "o spawn não foi setado no ponto de pesca"


class RelogActions:
    """Mouse, teclado e tela que o Relogger pede, em cima da pesca (Fisher).

    O Relogger trabalha em pixels do print; aqui soma a origem da janela do Roblox.
    """

    def __init__(self, fisher) -> None:
        self.f = fisher
        self._origin = (0, 0)

    # Modo Parsec: cada leitura/clique acontece com a janela da macro e o overlay transparentes
    # e sem pegar clique (o PLAY do menu fica embaixo deles). Fora dele, hidden() não faz nada.
    def grab(self):
        r = self.f.rect()
        self._origin = (r.x, r.y)
        with capture_mode.hidden():
            return r.x, r.y, self.f.grabber.grab(r)

    def _abs(self, x: int, y: int) -> tuple[int, int]:
        return self._origin[0] + int(x), self._origin[1] + int(y)

    def click(self, x: int, y: int) -> bool:
        with capture_mode.hidden():
            return bool(screen.click_at(*self._abs(x, y)))  # False = o cursor não chegou (mouse em uso)

    def mouse_down(self, x: int, y: int) -> bool:
        with capture_mode.hidden():
            if not screen.move_to(*self._abs(x, y)):
                return False  # não segura o botão onde o cursor estiver
            self.f.mouse.set(True)
            return True

    def mouse_up(self) -> None:
        self.f.mouse.release()

    def type_text(self, text: str) -> None:
        with capture_mode.hidden():
            screen.type_text(text)

    def press(self, key: str) -> None:
        with capture_mode.hidden():
            screen.tap_key(key)

    def sleep(self, sec: float) -> None:
        self.f.sleep(sec)

    def now(self) -> float:
        return time.perf_counter()

    def in_game(self, frame: np.ndarray) -> bool:
        return False  # o Relogger confirma a volta pela tela "desconhecida" por alguns segundos

    def status(self, msg: str) -> None:
        self.f.cb.status(msg)


def set_spawn(f) -> spawn.SpawnResult:
    """Seta o spawn (gamepass) onde o personagem está, pelos comandos do jogo.

    Erro no meio (OCR etc.): tenta fechar a caixinha, para a pesca não apertar a tecla da
    vara/T dentro dela, e devolve falha. F1 (StopRun) passa direto."""
    actions = RelogActions(f)
    try:
        return spawn.Setter(actions).run()
    except StopRun:
        raise
    except Exception as exc:
        log.exception("Erro ao setar o spawn")
        _close_command_box(actions)
        return spawn.SpawnResult(False, f"erro inesperado ({type(exc).__name__})")


def _close_command_box(actions: RelogActions) -> None:
    try:
        _, _, frame = actions.grab()
        s = spawn.classify(frame)
        if s.cancel_pos is not None:
            actions.click(*s.cancel_pos)
    except StopRun:
        raise
    except Exception:
        log.exception("Também não consegui fechar a caixinha de comandos")


def not_ready_reason(cfg: dict) -> str | None:
    """Por que o auto relog não pode rodar (None = pode)."""
    r = cfg.get("relog", {})
    if not r.get("enabled"):
        return "auto relog desligado"
    if not r.get("has_spawn_gamepass"):
        return "precisa do gamepass de spawn"
    if r.get("server_mode") == "nick" and not str(r.get("owner_nick", "")).strip():
        return "falta o nick do dono do servidor"
    if not r.get("spawn_set"):
        return SPAWN_NOT_SET  # por último: esse a macro resolve sozinha (seta depois do 1º peixe)
    return None


def lost_game_screen(img: np.ndarray | None, cfg: dict | None = None) -> relog.Screen | None:
    """Menu principal ou dialog "Disconnected" de verdade (com botão) na tela?"""
    s = relog.classify(img, cfg)
    if s.kind in ("main_menu", "game_loading"):
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
    if capture_mode.active():
        img = _clean_frame(f, img)
    return _handle(f, img)


def _clean_frame(f, img: np.ndarray | None) -> np.ndarray | None:
    """Modo Parsec: print novo com a macro transparente (o overlay fica em cima do PLAY do menu).
    Não espera o Roblox voltar: sem o jogo na tela, confere no print que já tinha."""
    try:
        r = window.client_rect(f.hwnd) if getattr(f, "hwnd", None) else None
        if r is None:
            return img
        with capture_mode.hidden():
            return f.grabber.grab(r)
    except Exception:
        log.exception("Não consegui tirar um print limpo; confiro no anterior")
        return img


DEFAULT_LOADING_TIMEOUT_SEC = 300.0
LOADING_POLL_SEC = 1.0


def _now() -> float:
    return time.perf_counter()


def _skip_loading(f) -> bool:
    """Tela de carregamento do jogo (25/09: a pesca ficou "não consegui equipar a vara" com o
    jogo carregando). Clica em "Skip loading!" e espera o jogo aparecer por `settle_sec`; cada
    PC demora um tanto, então o limite é folgado e configurável (relog.loading_timeout_sec)."""
    r = f.cfg.get("relog", {})
    timeout = float(r.get("loading_timeout_sec", DEFAULT_LOADING_TIMEOUT_SEC))
    settle = float(r.get("settle_sec", relog.DEFAULTS["settle_sec"]))
    actions = RelogActions(f)
    log.info("Tela de carregamento do jogo: clicando em Skip loading e esperando o jogo.")
    start, last_click, normal_since = _now(), None, None
    while _now() - start < timeout:
        _, _, frame = actions.grab()
        s = relog.classify(frame, r)
        now = _now()
        if s.kind == "game_loading":
            normal_since = None
            if s.skip_pos and (last_click is None or now - last_click >= relog.CLICK_COOLDOWN_SEC):
                actions.click(*s.skip_pos)
                last_click = now
        elif s.kind == "unknown":  # jogo normal de novo
            normal_since = normal_since if normal_since is not None else now
            if now - normal_since >= settle:
                log.info("Carregou: voltando a pescar.")
                return True
        else:
            return False  # caiu para outra tela (menu/desconectado): a próxima conferência cuida
        f.sleep(LOADING_POLL_SEC)
    log.warning("O jogo ficou carregando mais de %.0fs.", timeout)
    return False


def _handle(f, img: np.ndarray | None) -> bool:
    try:
        s = lost_game_screen(img, f.cfg.get("relog"))
    except Exception:  # OCR falhou: segue como um problema comum
        log.exception("Não consegui conferir se o jogo caiu")
        return False
    if s is None:
        return False
    if s.kind == "game_loading":
        return _skip_loading(f)  # carregar não é cair do jogo: não depende do auto relog
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
        f.after_relog = True  # se nem assim pegar peixe, o spawn está longe da água
        f._relog_failed = 0
        return True
    if result.reason == "codigo_sem_reconexao":
        _stop_for_good(f, f"{what}; esse código não reconecta sozinho")
    msg = f"não consegui reconectar sozinho ({result.reason})"
    log.error(msg)
    f._notify(f"🛑 {msg}. Tento de novo no próximo reinício automático.")
    raise StopRun("Parei: " + msg)
