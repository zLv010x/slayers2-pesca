"""Acha a janela do Roblox pelo PROCESSO (RobloxPlayerBeta.exe), não pelo título.

A macro antiga aceitava qualquer janela com "roblox" no título, então uma aba
do navegador ou um vídeo do YouTube sobre Roblox podia ser confundida com o jogo.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

ROBLOX_EXE = "robloxplayerbeta.exe"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
MIN_CLIENT_PX = 200
GA_ROOT = 2
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def ensure_dpi_awareness() -> None:
    """Sem isso, em telas com zoom (125%, 150%) as coordenadas saem erradas."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def find_roblox() -> int | None:
    """Devolve o HWND da janela visível do Roblox, ou None."""
    found: list[int] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd) and _process_name(hwnd) == ROBLOX_EXE:
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(_EnumProc(callback), 0)
    return found[0] if found else None


def client_rect(hwnd: int) -> Rect | None:
    """Área de jogo (sem barra de título) em coordenadas de tela."""
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < MIN_CLIENT_PX or h < MIN_CLIENT_PX:
        return None
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return Rect(pt.x, pt.y, w, h)


def set_capture_excluded(tk_widget, on: bool) -> bool:
    """Deixa a janela da macro invisível para prints de tela (a macro não se vê por cima
    do Roblox). Precisa do Windows 10 2004+; devolve False se não deu."""
    try:
        hwnd = user32.GetAncestor(tk_widget.winfo_id(), GA_ROOT)
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
    except (OSError, AttributeError):
        return False


def keep_awake(on: bool) -> None:
    """Impede o PC de dormir e a tela de apagar enquanto a macro roda (tela apagada = macro cega)."""
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
    kernel32.SetThreadExecutionState(flags)


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


def focus(hwnd: int) -> bool:
    """Traz o Roblox para frente. Devolve True se conseguiu."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if is_foreground(hwnd):
        return True
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    cur_tid = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid) and fg_tid != cur_tid and bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
    return is_foreground(hwnd)
