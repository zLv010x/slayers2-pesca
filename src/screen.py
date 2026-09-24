"""Captura da área do jogo e envio de mouse/teclado para o Roblox."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import keyboard
import mss
import numpy as np

from window import Rect

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
# O Roblox só "vê" o cursor depois de um pequeno movimento real.
NUDGE_SEC = 0.02
SETTLE_SEC = 0.05
CLICK_HOLD_SEC = 0.05
TYPE_DELAY_SEC = 0.04


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


def _mouse(flags: int) -> None:
    inp = _INPUT(type=INPUT_MOUSE)
    inp.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


class Grabber:
    """Tira prints da área do jogo. Reusar a mesma instância é bem mais rápido."""

    def __init__(self) -> None:
        self._sct = mss.MSS()

    def grab(self, rect: Rect) -> np.ndarray:
        shot = self._sct.grab({"left": rect.x, "top": rect.y, "width": rect.w, "height": rect.h})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        self._sct.close()


def move_to(x: int, y: int) -> None:
    user32.SetCursorPos(int(x) + 1, int(y) + 1)
    time.sleep(NUDGE_SEC)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(SETTLE_SEC)


def click_at(x: int, y: int) -> None:
    move_to(x, y)
    _mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(CLICK_HOLD_SEC)
    _mouse(MOUSEEVENTF_LEFTUP)


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
