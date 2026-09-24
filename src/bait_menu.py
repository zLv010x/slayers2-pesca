"""Mexe no menu do jogo para conferir e trocar a isca.

Caminho: M abre o menu → Inventory → aba Fishing → busca o nome da isca →
lê a quantidade (e o selo "✓ Bait") → se for trocar, clica no quadrado e em
"Equip Bait" → fecha com "Close".

Segurança: só clica em textos lidos na tela que batem com o esperado, e nunca
em "Back To Main Menu" / "Servers" (sairia do jogo ou trocaria de servidor).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

import inventory
import loot
import ocr
import screen

if TYPE_CHECKING:
    from cycle import Fisher

MENU_KEY = "m"
SEARCH_RX = r"item name here"
INVENTORY_RX = r"^\W*inventory$"
FISHING_RX = r"^fishing\s*\("
CLOSE_RX = r"close$"
EQUIP_RX = r"equip\s*bait"
FORBIDDEN_RX = re.compile(r"main menu|servers|back to", re.IGNORECASE)
LEFT_MENU_MAX_X = 0.25          # "Inventory" e "Close" ficam na coluna da esquerda
TABS_MAX_X = 0.45               # abas (All, Equipped, Fishing...) ficam antes da grade
WAIT_MENU = 1.0
WAIT_CLICK = 0.6
WAIT_SEARCH = 0.9
CLEAR_KEYS = 30


class MenuError(Exception):
    """Não foi possível chegar na tela certa do menu."""


@dataclass(frozen=True)
class BaitInfo:
    owned: bool
    count: int | None
    equipped: bool


class BaitMenu:
    def __init__(self, fisher: "Fisher") -> None:
        self.f = fisher
        self.search_box: ocr.Line | None = None

    # ------------------------------------------------------------ utilidades
    def _read(self):
        rect, img = self.f.frame()
        return rect, img, ocr.read_lines(img)

    def _click(self, rect, line: ocr.Line) -> None:
        if FORBIDDEN_RX.search(line.text):
            raise MenuError(f"clique recusado por segurança em {line.text!r}")
        screen.click_at(rect.x + line.x + line.w // 2, rect.y + line.y + line.h // 2)
        self.f.sleep(WAIT_CLICK)

    @staticmethod
    def _find(lines, pattern: str, img: np.ndarray, max_x: float | None = None) -> ocr.Line | None:
        line = inventory.find_line(lines, pattern)
        if line is None or (max_x is not None and line.x > max_x * img.shape[1]):
            return None
        return line

    # ------------------------------------------------------------ navegação
    def open(self) -> None:
        """Abre o menu e deixa em Inventory → Fishing. Lança MenuError se não conseguir."""
        screen.tap_key(MENU_KEY)
        self.f.sleep(WAIT_MENU)
        for _ in range(2):
            rect, img, lines = self._read()
            inv = self._find(lines, INVENTORY_RX, img, LEFT_MENU_MAX_X)
            if inv is not None:
                self._click(rect, inv)
                rect, img, lines = self._read()
            fishing = self._find(lines, FISHING_RX, img, TABS_MAX_X)
            if fishing is not None:
                self._click(rect, fishing)
                rect, img, lines = self._read()
            self.search_box = inventory.find_line(lines, SEARCH_RX)
            if self.search_box is not None and fishing is not None:
                return
        raise MenuError("não achei Inventory → Fishing no menu (a tecla M abriu o menu?)")

    def close(self) -> None:
        if self.search_box is None:
            _, _, lines = self._read()
            if inventory.find_line(lines, SEARCH_RX) is None:
                return
        self._clear_search()
        rect, img, lines = self._read()
        close = self._find(lines, CLOSE_RX, img, LEFT_MENU_MAX_X)
        if close is not None:
            self._click(rect, close)
        else:
            screen.tap_key(MENU_KEY)
            self.f.sleep(WAIT_MENU)
        self.search_box = None

    def _type_search(self, text: str) -> None:
        rect, _ = self.f.frame()
        box = self.search_box
        screen.click_at(rect.x + box.x + box.w // 2, rect.y + box.y + box.h // 2)
        self.f.sleep(0.2)
        for _ in range(CLEAR_KEYS):
            screen.tap_key("backspace", hold_sec=0.01)
        if text:
            screen.type_text(text)
        self.f.sleep(WAIT_SEARCH)

    def _clear_search(self) -> None:
        if self.search_box is not None:
            self._type_search("")

    # ------------------------------------------------------------ iscas
    def inspect(self, name: str) -> BaitInfo:
        self._type_search(name)
        _, img = self.f.frame()
        box = inventory.find_single_tile(img, self.search_box)
        if box is None:
            return BaitInfo(False, 0, False)
        tile = img[box.y:box.y + box.h, box.x:box.x + box.w]
        return BaitInfo(True, inventory.read_count(tile), inventory.has_bait_badge(tile))

    def equip(self, name: str) -> bool:
        """Equipa a isca. Devolve True se o selo "✓ Bait" apareceu nela."""
        self._type_search(name)
        rect, img = self.f.frame()
        box = inventory.find_single_tile(img, self.search_box)
        if box is None:
            return False
        cx, cy = box.center
        screen.click_at(rect.x + cx, rect.y + cy)
        self.f.sleep(WAIT_CLICK)
        rect, img = self.f.frame()
        half = img.shape[0] // 2
        lines = ocr.read_lines(loot._white_text(img[half:]))
        button = inventory.find_line(lines, EQUIP_RX)
        if button is None:
            return False
        self._click(rect, ocr.Line(button.text, button.x, button.y + half, button.w, button.h))
        return self.inspect(name).equipped
