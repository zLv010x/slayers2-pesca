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
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
MIN_CLIENT_PX = 200
GA_ROOT = 2
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_APPWINDOW = 0x40000
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
# SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED: só reaplica o estilo
SWP_STYLE_ONLY = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
# SWP_NOSIZE | SWP_NOACTIVATE: só muda o lugar (e mantém por cima de tudo)
SWP_MOVE_ONLY = 0x0001 | 0x0010
HWND_TOPMOST = ctypes.c_void_p(-1)

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


def set_app_id(app_id: str) -> None:
    """Identidade própria na barra de tarefas (sem isso o Windows mostra o ícone do Python)."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except (AttributeError, OSError):
        pass  # Windows antigo: fica o ícone do Python, a macro funciona igual


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


def root_hwnd(tk_widget) -> int:
    """Janela de verdade (topo) de um widget do Tk."""
    return user32.GetAncestor(tk_widget.winfo_id(), GA_ROOT)


def set_capture_excluded(tk_widget, on: bool) -> bool:
    """Deixa a janela da macro invisível para prints de tela (a macro não se vê por cima
    do Roblox). Precisa do Windows 10 2004+; devolve False se não deu."""
    try:
        hwnd = root_hwnd(tk_widget)
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
    except (OSError, AttributeError):
        return False


LWA_ALPHA = 0x2
OPAQUE = 255


def visible_rect(hwnd: int) -> Rect | None:
    """Retângulo da janela na tela, se ela estiver aparecendo (None = oculta ou minimizada)."""
    if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def get_alpha(hwnd: int) -> int:
    """Opacidade atual (0-255). Janela sem transparência nenhuma = 255."""
    alpha, flags = ctypes.c_ubyte(OPAQUE), wintypes.DWORD(0)
    if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED and user32.GetLayeredWindowAttributes(
            hwnd, None, ctypes.byref(alpha), ctypes.byref(flags)) and flags.value & LWA_ALPHA:
        return alpha.value
    return OPAQUE


def set_alpha(hwnd: int, alpha: int) -> bool:
    """Muda a opacidade direto no Windows (pode ser chamada fora da thread do Tk)."""
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not style & WS_EX_LAYERED:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        return bool(user32.SetLayeredWindowAttributes(hwnd, 0, max(0, min(OPAQUE, int(alpha))), LWA_ALPHA))
    except (OSError, AttributeError):
        return False


def set_overlay_style(tk_widget, clickthrough: bool) -> bool:
    """Janela que não rouba o foco do Roblox nem aparece na barra de tarefas;
    com `clickthrough`, os cliques passam direto para o que estiver embaixo."""
    try:
        hwnd = root_hwnd(tk_widget)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
        style = style | WS_EX_TRANSPARENT if clickthrough else style & ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        return bool(user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_STYLE_ONLY))
    except (OSError, AttributeError):
        return False


def show_no_activate(tk_widget, visible: bool) -> None:
    """Mostra/esconde sem ativar a janela (o deiconify do Tk ativaria e tiraria o Roblox da frente)."""
    user32.ShowWindow(root_hwnd(tk_widget), SW_SHOWNOACTIVATE if visible else SW_HIDE)


def move_no_activate(tk_widget, x: int, y: int) -> None:
    """Move pelo Windows direto (com a janela escondida por fora do Tk, o geometry do Tk não move)."""
    user32.SetWindowPos(root_hwnd(tk_widget), HWND_TOPMOST, int(x), int(y), 0, 0, SWP_MOVE_ONLY)


def window_xy(tk_widget) -> tuple[int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(root_hwnd(tk_widget), ctypes.byref(r))
    return r.left, r.top


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
