"""Captura da área do jogo e envio de mouse/teclado para o Roblox."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

import keyboard
import mss
import numpy as np

from window import Rect

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
MONITOR_DEFAULTTONULL = 0
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
# O Roblox só "vê" o cursor depois de um movimento de mouse de verdade.
NUDGE_PX = 3
MOVE_TRIES = 3
MOVE_TOLERANCE_PX = 2
NUDGE_SEC = 0.03
SETTLE_SEC = 0.05
CLICK_HOLD_SEC = 0.05
TYPE_DELAY_SEC = 0.04
# "esperar o mouse ficar livre": botões soltos e cursor parado por isso, até o limite.
WAIT_FREE_SETTLE_SEC = 0.3
WAIT_FREE_TIMEOUT_SEC = 5.0
WAIT_FREE_POLL_SEC = 0.05

user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
user32.GetAsyncKeyState.restype = wintypes.SHORT
user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = (("mi", _MOUSEINPUT),)
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _U))


def _mouse(flags: int, dx: int = 0, dy: int = 0) -> None:
    inp = _INPUT(type=INPUT_MOUSE)
    inp.mi = _MOUSEINPUT(int(dx), int(dy), 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def on_monitor(x: int, y: int) -> bool:
    """True se (x, y) cai em algum monitor ligado (a janela pode ter saído da tela)."""
    return user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONULL) is not None


def buttons_held() -> bool:
    """True se o botão esquerdo ou o direito do mouse está fisicamente apertado agora."""
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000 or user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)


@dataclass(frozen=True)
class MoveResult:
    """Resultado de move_to/click_at: motivo da falha e onde o cursor ficou.

    Avaliável como bool (`if not resultado:`) para quem só precisa saber se deu certo.
    """
    ok: bool
    reason: str  # "ok" | "mexendo" | "preso" | "fora_do_monitor"
    pos: tuple[int, int]

    def __bool__(self) -> bool:
        return self.ok


def _move_event(x: int, y: int) -> None:
    """Movimento "de verdade" (como um mouse físico) até (x, y) na área de trabalho inteira."""
    vx, vy = user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw, vh = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    nx = round((x - vx) * 65535 / max(1, vw - 1))
    ny = round((y - vy) * 65535 / max(1, vh - 1))
    _mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)


class Grabber:
    """Tira prints da área do jogo. Reusar a mesma instância é bem mais rápido."""

    def __init__(self) -> None:
        self._sct = mss.MSS()

    def grab(self, rect: Rect) -> np.ndarray:
        shot = self._sct.grab({"left": rect.x, "top": rect.y, "width": rect.w, "height": rect.h})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        self._sct.close()


def move_to(x: int, y: int) -> MoveResult:
    """Leva o cursor até (x, y) e confere que chegou.

    O Roblox não percebe o cursor "teletransportado" (SetCursorPos): ele usa a última
    posição de um movimento de mouse de verdade. Por isso mandamos eventos de movimento
    (passando por um ponto do lado, para o jogo ver o mouse andar) e conferimos a posição.

    Se não chegar, o motivo vem em `reason`: "fora_do_monitor" (o ponto nem está numa
    tela ligada: a janela do Roblox deve ter saído da área visível), "mexendo" (o cursor
    mudou sozinho entre duas leituras, sem a macro mandar nada: alguém está usando o
    mouse) ou "preso" (parado fora do alvo, ex.: botão do mouse segurado girando a câmera).
    """
    x, y = int(x), int(y)
    if not on_monitor(x, y):
        return MoveResult(False, "fora_do_monitor", cursor_pos())
    # o desvio inicial pode cair fora do monitor perto das bordas: tenta o lado oposto
    nudge = NUDGE_PX if on_monitor(x + NUDGE_PX, y + NUDGE_PX) else -NUDGE_PX
    for attempt in range(MOVE_TRIES):
        _move_event(x + nudge, y + nudge)
        time.sleep(NUDGE_SEC)
        _move_event(x, y)
        time.sleep(SETTLE_SEC)
        cx, cy = cursor_pos()
        if abs(cx - x) <= MOVE_TOLERANCE_PX and abs(cy - y) <= MOVE_TOLERANCE_PX:
            return MoveResult(True, "ok", (cx, cy))
        if attempt < MOVE_TRIES - 1:
            user32.SetCursorPos(x, y)  # último recurso antes de tentar os eventos de novo
            time.sleep(NUDGE_SEC)
    # esgotou as tentativas: uma leitura a mais (sem mandar nada) diz se é o usuário mexendo
    last = (cx, cy)
    time.sleep(SETTLE_SEC)
    cx, cy = cursor_pos()
    if (cx, cy) != last:
        return MoveResult(False, "mexendo", (cx, cy))
    return MoveResult(False, "preso", (cx, cy))


def click_at(x: int, y: int) -> MoveResult:
    """Clica em (x, y). Não clica se o cursor não chegou lá (motivo em `.reason`)."""
    result = move_to(x, y)
    if not result.ok:
        return result
    _mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(CLICK_HOLD_SEC)
    _mouse(MOUSEEVENTF_LEFTUP)
    return result


def wait_mouse_free(timeout: float = WAIT_FREE_TIMEOUT_SEC,
                     sleep: Callable[[float], None] = time.sleep) -> bool:
    """Espera os botões soltos e o cursor parado por WAIT_FREE_SETTLE_SEC, até `timeout`.

    Devolve True se o mouse ficou livre, False se estourou o tempo (a macro segue mesmo
    assim: é melhor esforço, não trava para sempre). `sleep` é quem espera entre as
    conferências: o Fisher passa self.sleep, que interrompe a espera se pedirem para parar.
    """
    deadline = time.perf_counter() + timeout
    still_since: float | None = None
    last = cursor_pos()
    while True:
        pos = cursor_pos()
        if pos == last and not buttons_held():
            if still_since is None:
                still_since = time.perf_counter()
            elif time.perf_counter() - still_since >= WAIT_FREE_SETTLE_SEC:
                return True
        else:
            still_since = None
        last = pos
        if time.perf_counter() >= deadline:
            return False
        sleep(WAIT_FREE_POLL_SEC)


class MouseButton:
    """Segura/solta o botão esquerdo lembrando o estado, para nunca ficar preso."""

    def __init__(self) -> None:
        self.held = False

    def set(self, hold: bool) -> None:
        if hold and not self.held:
            _mouse(MOUSEEVENTF_LEFTDOWN)
            self.held = True
        elif not hold and self.held:
            _mouse(MOUSEEVENTF_LEFTUP)
            self.held = False

    def release(self) -> None:
        # Manda o "soltar" mesmo que ache que já está solto: garante que não trava.
        _mouse(MOUSEEVENTF_LEFTUP)
        self.held = False


def send_combo(combo: str) -> None:
    """Atalho tipo "ctrl+a"."""
    keyboard.send(combo)
    time.sleep(NUDGE_SEC)


def tap_key(key: str, hold_sec: float = 0.08) -> None:
    keyboard.release(key)
    keyboard.press(key)
    time.sleep(hold_sec)
    keyboard.release(key)


def type_text(text: str) -> None:
    keyboard.write(text, delay=TYPE_DELAY_SEC)


def press_key(key: str) -> None:
    keyboard.press(key)


def release_key(key: str) -> None:
    keyboard.release(key)
