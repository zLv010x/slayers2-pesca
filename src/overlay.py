"""Overlay: janelinha por cima do jogo com o tempo de macro, peixes, itens e iscas gastas.

- O lugar padrão é em cima do painel da party (a área que a macro nunca clica).
- Dá para arrastar; a posição fica em fração da janela do Roblox, então o
  overlay acompanha o jogo quando a janela muda de lugar ou de tamanho.
- Invisível para a captura de tela: não atrapalha a leitura nem aparece nos prints.
- Nunca rouba o foco do Roblox. Enquanto a macro pesca, os cliques atravessam
  o overlay (ele não segura clique nenhum da macro); parado, dá para arrastar.
"""
from __future__ import annotations

import re
import tkinter as tk
from collections import Counter
from typing import Callable, NamedTuple

import window
from window import Rect

MAX_FRAC = 0.95           # o overlay não sai da janela do jogo
POS_DECIMALS = 4
PARTY_MARGIN = 0.005      # afasta um pouco da borda esquerda
MAX_ROWS = 8              # linhas por seção; o resto vira "+N outros"
ALPHA = 0.88
BG, FG, HEAD, MUTED, QTY = "#111827", "#e5e7eb", "#93c5fd", "#9ca3af", "#fbbf24"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 12)

# Peixes que não têm "fish" no nome (Krathulon e Crustadon são os lendários da missão do Isao).
FISH_NAMES = {"krathulon", "crustadon", "seahorse"}


class Line(NamedTuple):
    text: str
    style: str               # title | head | row | more | empty
    qty: int | None = None


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def kind_of(name: str) -> str:
    key = _normalize(name)
    return "peixe" if "fish" in key or key in FISH_NAMES else "item"


def _sorted_rows(counts: Counter) -> list[tuple[str, int]]:
    rows = [(name, qty) for name, qty in counts.items() if name.strip() and qty > 0]
    return sorted(rows, key=lambda r: (-r[1], r[0].lower()))


def split_counts(counts: Counter) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    rows = _sorted_rows(counts)
    fish = [r for r in rows if kind_of(r[0]) == "peixe"]
    items = [r for r in rows if kind_of(r[0]) == "item"]
    return fish, items


def trim(rows: list, limit: int) -> tuple[list, int]:
    return rows[:limit], max(0, len(rows) - limit)


def _section(title: str, rows: list[tuple[str, int]], max_rows: int) -> list[Line]:
    if not rows:
        return []
    shown, rest = trim(rows, max_rows)
    out = [Line(f"{title} ({sum(q for _, q in rows)})", "head")]
    out += [Line(name, "row", qty) for name, qty in shown]
    if rest:
        out.append(Line(f"+{rest} outros", "more"))
    return out


def build_lines(elapsed: str, counts: Counter, baits_used: Counter, max_rows: int = MAX_ROWS) -> list[Line]:
    fish, items = split_counts(counts)
    lines = [Line(f"⏱ {elapsed}", "title")]
    if not fish and not items:
        lines.append(Line("Nada pego ainda", "empty"))
    lines += _section("Peixes", fish, max_rows)
    lines += _section("Itens", items, max_rows)
    lines += _section("Iscas gastas", _sorted_rows(baits_used), max_rows)
    return lines


# ---------------------------------------------------------------- posição
def default_pos(zone: dict) -> dict:
    return {"x": round(zone["x0"] + PARTY_MARGIN, POS_DECIMALS), "y": round(zone["y0"], POS_DECIMALS)}


def valid_pos(pos) -> dict | None:
    if not isinstance(pos, dict):
        return None
    out = {}
    for key in ("x", "y"):
        value = pos.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            return None
        out[key] = float(value)
    return out


def to_screen(r: Rect, pos: dict) -> tuple[int, int]:
    return r.x + round(pos["x"] * r.w), r.y + round(pos["y"] * r.h)


def from_screen(r: Rect, x: int, y: int) -> dict:
    def frac(value: int, start: int, size: int) -> float:
        return round(min(MAX_FRAC, max(0.0, (value - start) / max(1, size))), POS_DECIMALS)
    return {"x": frac(x, r.x, r.w), "y": frac(y, r.y, r.h)}


# ---------------------------------------------------------------- janela
class Overlay(tk.Toplevel):
    """Só mostra; quem decide o conteúdo e a hora de atualizar é o app (`refresh`/`follow`)."""

    def __init__(self, master, get_rect: Callable[[], Rect | None],
                 on_moved: Callable[[dict], None], zone: dict, pos: dict | None) -> None:
        super().__init__(master)
        self.withdraw()
        self.title("Slayers 2 • Overlay")
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # só some pela opção na macro
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", ALPHA)
        self.configure(bg=BG)
        self._get_rect = get_rect
        self._on_moved = on_moved
        self._zone = zone
        self._pos = valid_pos(pos)
        self._lines: list[Line] | None = None
        self._drag: tuple[int, int] | None = None
        self._clickthrough = False
        self._visible = False
        self._body = tk.Frame(self, bg=BG, padx=10, pady=6)
        self._body.pack()
        self._bind_drag(self)
        self._bind_drag(self._body)
        self._first_show()

    def _first_show(self) -> None:
        """Mostra uma vez (invisível) só para aplicar os estilos; depois só aparece/some sem ativar."""
        self.attributes("-alpha", 0.0)
        self.deiconify()
        self.update_idletasks()
        window.set_capture_excluded(self, True)
        window.set_overlay_style(self, clickthrough=False)
        window.show_no_activate(self, False)
        self.attributes("-alpha", ALPHA)

    # ------------------------------------------------------------ conteúdo
    def refresh(self, lines: list[Line]) -> None:
        if lines == self._lines:
            return
        self._lines = lines
        for child in self._body.winfo_children():
            child.destroy()
        for row, line in enumerate(lines):
            self._add_line(row, line)

    def _add_line(self, row: int, line: Line) -> None:
        styles = {
            "title": (FONT_TITLE, FG, 0), "head": (FONT_BOLD, HEAD, 4),
            "row": (FONT, FG, 0), "more": (FONT, MUTED, 0), "empty": (FONT, MUTED, 2),
        }
        font, color, top = styles.get(line.style, (FONT, FG, 0))
        indent = 10 if line.style in ("row", "more") else 0
        label = tk.Label(self._body, text=line.text, font=font, fg=color, bg=BG, anchor="w")
        span = 1 if line.qty is not None else 2
        label.grid(row=row, column=0, columnspan=span, sticky="w", padx=(indent, 0), pady=(top, 0))
        self._bind_drag(label)
        if line.qty is not None:
            qty = tk.Label(self._body, text=str(line.qty), font=FONT_BOLD, fg=QTY, bg=BG, anchor="e")
            qty.grid(row=row, column=1, sticky="e", padx=(12, 0))
            self._bind_drag(qty)

    # ------------------------------------------------------------ lugar
    def follow(self) -> None:
        """Acompanha a janela do Roblox; some quando `get_rect` diz que não é para mostrar."""
        r = self._get_rect()
        if r is None:
            self.hide()
            return
        if self._drag is None:
            window.move_no_activate(self, *to_screen(r, self._pos or default_pos(self._zone)))
        if not self._visible:
            window.show_no_activate(self, True)
            self._visible = True

    def hide(self) -> None:
        if self._visible:
            window.show_no_activate(self, False)
            self._visible = False
            self._drag = None

    def reset_position(self) -> None:
        self._pos = None
        self.follow()

    def set_clickthrough(self, on: bool) -> None:
        self._clickthrough = on
        if on:
            self._drag = None
        window.set_overlay_style(self, clickthrough=on)

    # ------------------------------------------------------------ arrastar
    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)
        widget.bind("<ButtonRelease-1>", self._drag_end)

    def _drag_start(self, event: tk.Event) -> None:
        if not self._clickthrough:
            x, y = window.window_xy(self)
            self._drag = (event.x_root - x, event.y_root - y)

    def _drag_move(self, event: tk.Event) -> None:
        if self._drag is not None:
            window.move_no_activate(self, event.x_root - self._drag[0], event.y_root - self._drag[1])

    def _drag_end(self, _event: tk.Event) -> None:
        if self._drag is None:
            return
        self._drag = None
        r = self._get_rect()
        if r is not None:
            self._pos = from_screen(r, *window.window_xy(self))
            self._on_moved(self._pos)
