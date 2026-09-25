"""Telas por cima do jogo para marcar o ponto de lançamento e a área da barra."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from config import PARTY_ZONE
from i18n import _
from window import Rect

MIN_AREA_PX = 30
HANDLE_PX = 10
BANNER_BG = "#111827"
BANNER_FG = "#f9fafb"
PARTY_COLOR = "#ef4444"
AREA_COLOR = "#a855f7"
SAVE_COLOR = "#16a34a"
CANCEL_COLOR = "#4b5563"


class PointPicker(tk.Toplevel):
    """Cobre a janela do Roblox; um clique marca o ponto (em fração da área)."""

    def __init__(self, master: tk.Misc, game: Rect, prompt: str,
                 on_done: Callable[[tuple[float, float] | None], None]) -> None:
        super().__init__(master)
        self.game = game
        self.on_done = on_done
        self._finished = False
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        self.geometry(f"{game.w}x{game.h}+{game.x}+{game.y}")
        canvas = tk.Canvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)
        z = PARTY_ZONE
        canvas.create_rectangle(z["x0"] * game.w, z["y0"] * game.h, z["x1"] * game.w, z["y1"] * game.h,
                                outline=PARTY_COLOR, width=3, fill=PARTY_COLOR, stipple="gray25")
        canvas.create_text(z["x1"] * game.w / 2, z["y0"] * game.h - 14, fill=PARTY_COLOR,
                           text=_("party: não clica aqui"), font=("Segoe UI", 12, "bold"))
        canvas.create_text(game.w / 2, 60, text=prompt + _("\nClique para marcar  •  Esc cancela"),
                           fill=BANNER_FG, font=("Segoe UI", 18, "bold"), justify="center")
        canvas.bind("<Button-1>", self._click)
        # Botão de cancelar visível: o Esc pode não chegar se o Roblox estiver com o teclado.
        cancel = tk.Button(canvas, text=_("✖ Cancelar"), command=lambda: self._finish(None), bg=CANCEL_COLOR,
                           fg="white", relief="flat", font=("Segoe UI", 12, "bold"), cursor="hand2")
        canvas.create_window(game.w / 2, 120, window=cancel)
        self.bind("<Escape>", lambda _e: self._finish(None))
        self.focus_force()
        self.grab_set()

    def _click(self, event: tk.Event) -> None:
        self._finish((event.x / self.game.w, event.y / self.game.h))

    def _finish(self, value: tuple[float, float] | None) -> None:
        if self._finished:
            return
        self._finished = True
        self.grab_release()
        self.destroy()
        self.on_done(value)


class AreaPicker(tk.Toplevel):
    """Retângulo arrastável para marcar onde a barra do minigame aparece."""

    def __init__(self, master: tk.Misc, game: Rect, initial: dict,
                 on_done: Callable[[dict | None], None]) -> None:
        super().__init__(master)
        self.game = game
        self.on_done = on_done
        self._finished = False
        self.x = int(game.x + initial["x"] * game.w)
        self.y = int(game.y + initial["y"] * game.h)
        self.w = max(MIN_AREA_PX, int(initial["w"] * game.w))
        self.h = max(MIN_AREA_PX, int(initial["h"] * game.h))
        self._mode = None
        self._start = (0, 0, 0, 0, 0, 0)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.5)
        self.configure(bg=AREA_COLOR)
        inner = tk.Frame(self, bg=BANNER_BG, cursor="fleur")
        inner.pack(fill="both", expand=True, padx=3, pady=3)
        # Botões de verdade: Enter/Esc não chegam aqui quando o Roblox está com o teclado.
        buttons = tk.Frame(inner, bg=BANNER_BG)
        buttons.pack(side="bottom", fill="x", padx=2, pady=4)
        tk.Button(buttons, text=_("✔ Salvar"), command=self._save, bg=SAVE_COLOR, fg="white",
                  activebackground=SAVE_COLOR, relief="flat", font=("Segoe UI", 9, "bold"),
                  cursor="hand2").pack(fill="x", pady=(0, 3))
        tk.Button(buttons, text=_("✖ Cancelar"), command=lambda: self._finish(None), bg=CANCEL_COLOR,
                  fg="white", activebackground=CANCEL_COLOR, relief="flat", font=("Segoe UI", 9),
                  cursor="hand2").pack(fill="x")
        label = tk.Label(inner, text=_("Barra do\nminigame\n\nArraste\npara mover\n\nCanto de\nbaixo =\ntamanho"),
                         bg=BANNER_BG, fg=BANNER_FG, font=("Segoe UI", 9, "bold"))
        label.pack(expand=True)
        for wdg in (self, inner, label):
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<B1-Motion>", self._drag)
        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self._finish(None))
        self._apply()
        self.focus_force()
        self.grab_set()

    def _apply(self) -> None:
        g = self.game
        self.w = max(MIN_AREA_PX, min(self.w, g.w))
        self.h = max(MIN_AREA_PX, min(self.h, g.h))
        self.x = max(g.x, min(self.x, g.x + g.w - self.w))
        self.y = max(g.y, min(self.y, g.y + g.h - self.h))
        self.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")

    def _press(self, event: tk.Event) -> None:
        lx, ly = event.x_root - self.x, event.y_root - self.y
        near_corner = lx >= self.w - 3 * HANDLE_PX and ly >= self.h - 3 * HANDLE_PX
        self._mode = "resize" if near_corner else "move"
        self._start = (event.x_root, event.y_root, self.x, self.y, self.w, self.h)

    def _drag(self, event: tk.Event) -> None:
        mx, my, x, y, w, h = self._start
        dx, dy = event.x_root - mx, event.y_root - my
        if self._mode == "move":
            self.x, self.y = x + dx, y + dy
        else:
            self.w, self.h = w + dx, h + dy
        self._apply()

    def _save(self) -> None:
        g = self.game
        self._finish({"x": (self.x - g.x) / g.w, "y": (self.y - g.y) / g.h,
                      "w": self.w / g.w, "h": self.h / g.h})

    def _finish(self, value: dict | None) -> None:
        if self._finished:
            return
        self._finished = True
        self.grab_release()
        self.destroy()
        self.on_done(value)
