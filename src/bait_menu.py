"""Mexe no menu do jogo para conferir e trocar a isca.

Caminho: M abre o menu → Inventory → aba Fishing → digita o nome da isca na
busca + Enter → lê a quantidade (e o selo "✓ Bait") → se for trocar, clica no
quadrado e em "Equip Bait" → limpa a busca e fecha no "Close".

Segurança:
- só clica em textos lidos na tela que batem com o esperado, e nunca em
  "Back To Main Menu" / "Servers" (sairia do jogo ou trocaria de servidor);
- confere cada passo (aba selecionada, busca filtrou, menu fechou); se algo não
  bater, desiste da conferência em vez de ler errado;
- com a caixa de busca ativa, qualquer tecla vira texto: por isso o menu precisa
  estar fechado de verdade antes de a pesca voltar a apertar teclas.
"""
from __future__ import annotations

import re
import time
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
INVENTORY_RX = r"\binventory$"   # o ícone ao lado às vezes vira uma letra ("O Inventory")
FISHING_RX = r"^fishing\s*\("
ALL_TAB_RX = r"^al[li1]\s*\("   # OCR lê "All (127)" como "Ali (127)"
CLOSE_RX = r"close$"
EQUIP_RX = r"equip\s*bait"
FORBIDDEN_RX = re.compile(r"main menu|servers|back to", re.IGNORECASE)
LEFT_MENU_MAX_X = 0.25          # "Inventory" e "Close" ficam na coluna da esquerda
TABS_MAX_X = 0.45               # abas (All, Equipped, Fishing...) ficam antes da grade
WAIT_MENU = 1.0
WAIT_CLICK = 0.6
WAIT_SEARCH = 1.0
CLEAR_KEYS = 30
BACKSPACE_HOLD_SEC = 0.03       # rápido demais o jogo perde teclas
BACKSPACE_GAP_SEC = 0.02
WAIT_TYPED = 0.4
TYPE_TRIES = 3
TAB_TRIES = 3
MENU_KEY_TRIES = 2
MENU_OPEN_TIMEOUT = 3.0
MENU_POLL = 0.4
CLOSE_TRIES = 3


class MenuError(Exception):
    """Não foi possível chegar na tela certa do menu (ou sair dela)."""


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
        self._click_xy(rect.x + line.x + line.w // 2, rect.y + line.y + line.h // 2, line.text)

    def _click_xy(self, x: int, y: int, what: str) -> None:
        if not screen.click_at(x, y):
            raise MenuError(f"o mouse não chegou em {what!r} ({x}, {y})")
        self.f.sleep(WAIT_CLICK)

    @staticmethod
    def _find(lines, pattern: str, img: np.ndarray, max_x: float | None = None) -> ocr.Line | None:
        line = inventory.find_line(lines, pattern)
        if line is None or (max_x is not None and line.x > max_x * img.shape[1]):
            return None
        return line

    def _menu_open(self, lines, img) -> bool:
        return (inventory.find_line(lines, SEARCH_RX) is not None
                or self._find(lines, INVENTORY_RX, img, LEFT_MENU_MAX_X) is not None)

    # ------------------------------------------------------------ navegação
    def _wait_inventory(self):
        """Espera o menu aparecer (às vezes demora). Devolve (rect, img, linha "Inventory") ou None."""
        end = time.perf_counter() + MENU_OPEN_TIMEOUT
        while True:
            rect, img, lines = self._read()
            inv = self._find(lines, INVENTORY_RX, img, LEFT_MENU_MAX_X)
            if inv is not None or time.perf_counter() >= end:
                return (rect, img, inv) if inv is not None else None
            self.f.sleep(MENU_POLL)

    def open(self) -> None:
        """Abre o menu e deixa em Inventory → aba de itens (Fishing, ou All se a Fishing
        estiver escondida numa janela pequena). Lança MenuError se não conseguir."""
        found, opened = None, False
        for _ in range(MENU_KEY_TRIES):   # o jogo às vezes ignora o primeiro M
            screen.tap_key(MENU_KEY)
            found = self._wait_inventory()
            if found is not None:
                break
            # abriu devagar (ou "Inventory" está coberto): outro M FECHARIA o menu
            _, img, lines = self._read()
            if self._menu_open(lines, img):
                opened = True
                break
        if found is not None:
            rect, _, inv = found
            self._click(rect, inv)
        elif not opened:
            raise MenuError("o menu não abriu com a tecla M")
        for _ in range(TAB_TRIES):
            rect, img, lines = self._read()
            # a busca por nome funciona em qualquer aba: se a Fishing não aparece
            # (lista de abas cortada em janela pequena), usa a All, que fica sempre no topo
            tab = (self._find(lines, FISHING_RX, img, TABS_MAX_X)
                   or self._find(lines, ALL_TAB_RX, img, TABS_MAX_X))
            if tab is None:
                raise MenuError("não achei a aba Fishing nem a All")
            if inventory.is_active_tab(img, tab):
                self.search_box = inventory.find_line(lines, SEARCH_RX)
                if self.search_box is None:
                    raise MenuError("não achei a caixa de busca")
                return
            self._click(rect, tab)
        raise MenuError(f"a aba {tab.text!r} não ficou selecionada")

    def close(self) -> None:
        """Limpa a busca e fecha o menu, conferindo que fechou mesmo."""
        if self.search_box is not None:
            try:
                self._type_search("")
            except MenuError:
                pass  # busca suja não pode impedir de fechar o menu
        for attempt in range(CLOSE_TRIES):
            rect, img, lines = self._read()
            if not self._menu_open(lines, img):
                self.search_box = None
                return
            close = self._find(lines, CLOSE_RX, img, LEFT_MENU_MAX_X)
            if close is not None and attempt < CLOSE_TRIES - 1:
                self._click(rect, close)
            else:
                screen.tap_key(MENU_KEY)
                self.f.sleep(WAIT_MENU)
        rect, img, lines = self._read()
        if self._menu_open(lines, img):
            raise MenuError("o menu não fechou")
        self.search_box = None

    def _clear_focused_box(self) -> None:
        """Apaga tudo da caixa: cursor no fim + selecionar tudo + backspaces sem pressa."""
        screen.tap_key("end")
        screen.send_combo("ctrl+a")
        for _ in range(CLEAR_KEYS):
            screen.tap_key("backspace", hold_sec=BACKSPACE_HOLD_SEC)
            self.f.sleep(BACKSPACE_GAP_SEC)

    def _type_search(self, text: str) -> None:
        """Deixa a busca com exatamente `text` e aperta Enter (o jogo só filtra com Enter).

        Confere lendo a caixa: se sobrou texto velho ou o jogo perdeu letras, apaga e
        digita de novo. Enter também tira o foco da caixa (senão as teclas viram texto).
        """
        got = ""
        for _ in range(TYPE_TRIES):
            rect, _ = self.f.frame()
            box = self.search_box
            self._click_xy(rect.x + box.x + box.w // 2, rect.y + box.y + box.h // 2, "busca")
            self._clear_focused_box()
            if text:
                screen.type_text(text)
            self.f.sleep(WAIT_TYPED)
            _, img = self.f.frame()
            got = inventory.read_search_text(img, box)
            if inventory.search_matches(got, text):
                screen.tap_key("enter")
                self.f.sleep(WAIT_SEARCH)
                return
        screen.tap_key("enter")
        raise MenuError(f"não consegui escrever {text!r} na busca (ficou {got!r})")

    def _search_one(self, name: str):
        """Busca o nome e devolve (rect, img, quadrado ou None). Erro se a busca não filtrou."""
        self._type_search(name)
        rect, img = self.f.frame()
        tiles = inventory.find_tiles(img, self.search_box)
        if len(tiles) > 1:
            raise MenuError(f"a busca por {name!r} não filtrou ({len(tiles)} itens na tela)")
        return rect, img, (tiles[0] if tiles else None)

    # ------------------------------------------------------------ iscas
    def inspect(self, name: str) -> BaitInfo:
        _, img, box = self._search_one(name)
        if box is None:
            return BaitInfo(False, 0, False)
        tile = img[box.y:box.y + box.h, box.x:box.x + box.w]
        return BaitInfo(True, inventory.read_count(tile), inventory.has_bait_badge(tile))

    def equip(self, name: str) -> bool:
        """Equipa a isca. Devolve True se o selo "✓ Bait" apareceu nela."""
        rect, img, box = self._search_one(name)
        if box is None:
            return False
        cx, cy = box.center
        self._click_xy(rect.x + cx, rect.y + cy, name)
        rect, img = self.f.frame()
        half = img.shape[0] // 2
        lines = ocr.read_lines(loot._white_text(img[half:]))
        button = inventory.find_line(lines, EQUIP_RX)
        if button is None:
            return False
        self._click(rect, ocr.Line(button.text, button.x, button.y + half, button.w, button.h))
        return self.inspect(name).equipped
