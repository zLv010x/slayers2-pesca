"""Seta o spawn (gamepass) no ponto de pesca pelos comandos do jogo.

Fluxo (prints do usuário, 24/09): botão "Commands" no alto da tela (≈13% da largura,
à esquerda; na janela estreita ≈43%) → vira
um X vermelho + a caixinha "command" (ainda não aceita texto) → clicar na caixinha abre
a lista de comandos (agora aceita) → digitar "set" + Enter → aparece X + "set" + ✓ verde
→ clicar no ✓ → volta ao normal. O "set" é digitado (e não clicado na lista) porque fora
do servidor VIP a lista é outra.

Segurança: só digita com a lista aberta (prova de que a caixinha está ativa; senão o
"S" iria para o jogo e andaria com o personagem para fora do ponto de pesca), só aperta
Enter lendo "set" na caixinha, nunca digita duas vezes, e ao desistir clica no X.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

import i18n
import ocr

# Parte de cima da tela inteira: o botão fica no alto e a lista desce ~25% da altura.
# Até 40%: o painel da party (que tem "PVP", uma palavra de comando) começa abaixo disso.
REGION_X = (0.0, 1.0)
REGION_Y = (0.0, 0.40)
OCR_UPSCALE = 2
# Faixa em volta do X, lida de novo bem ampliada: na interface menor o "set" (3 letras
# pequenas) some no OCR da região inteira.
STRIP_UP_DIAMS, STRIP_DOWN_DIAMS, STRIP_RIGHT_DIAMS = 1.5, 1.5, 9
STRIP_UPSCALE = 4
STRIP_MAX_BLOBS = 2
COMMAND_WORDS = {"access", "announce", "ban", "kick", "mod", "pve", "pvp", "set", "shutdown",
                 "unban", "unmod", "unset", "unwhitelist", "whitelist"}
# Ordem da lista no jogo (alfabética); fora do VIP a lista é menor, mas na mesma ordem.
COMMAND_ORDER = ["access", "announce", "ban", "kick", "mod", "pve", "pvp", "set", "shutdown",
                 "unban", "unmod", "unset", "unwhitelist", "whitelist"]
MIN_LIST_WORDS = 3
LIST_FIRST_GAP_LINES = 4   # 1º item logo abaixo da caixinha (até 4 alturas de texto)
LIST_COLUMN_WIDTHS = 1.5   # itens na coluna da caixinha (até 1,5 largura dela para o lado)
# Cores (HSV do OpenCV): X vermelho e ✓ verde
RED_HUE = (8, 172)       # vermelho = matiz <= 8 ou >= 172
GREEN_HUE = (45, 85)
MIN_SAT, MIN_VAL = 120, 120
MIN_BLOB_AREA = 30
ROUND_RATIO = (0.6, 1.6)  # X e ✓ são círculos
# "mesma linha" = centros a até 3 alturas de texto: o OCR erra a posição de palavras
# curtas ("set") em até ~25 px; um "set" da lista fica bem mais longe que isso.
ROW_TOL_LINES = 3.0
NEAR_LINES = 8            # X/✓ ficam a poucas alturas de texto da caixinha

POLL_SEC = 0.3
CLICK_COOLDOWN_SEC = 2.0
STEP_TIMEOUT_SEC = 6.0    # mesma tela por mais que isso = travou
TYPE_CONFIRM_SEC = 3.0    # digitou e a caixinha não mostrou "set"
NO_BUTTON_SEC = 5.0       # nem achou o botão Commands
TOTAL_TIMEOUT_SEC = 30.0
LIST_READS_TO_TYPE = 2     # lista aberta em leituras seguidas antes de digitar
MAX_READ_GAP_SEC = 1.0     # leitura atrasada (Roblox saiu da frente?) recomeça a contagem


@dataclass(frozen=True)
class SpawnScreen:
    kind: str  # normal | closed_box | list_open | typed | confirm | unknown
    commands_pos: tuple[int, int] | None = None
    pill_pos: tuple[int, int] | None = None
    cancel_pos: tuple[int, int] | None = None
    confirm_pos: tuple[int, int] | None = None


@dataclass(frozen=True)
class SpawnResult:
    ok: bool
    reason: str

    def __bool__(self) -> bool:
        return self.ok


def _squash(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _center(line: ocr.Line) -> tuple[int, int]:
    return line.x + line.w // 2, line.y + line.h // 2


def _round_blobs(mask: np.ndarray, ox: int, oy: int) -> list[tuple[int, int, int]]:
    """Círculos coloridos: (centro x, centro y, área) em pixels do frame."""
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    out = []
    for i in range(1, n):
        _, _, w, h, area = stats[i]
        if area >= MIN_BLOB_AREA and ROUND_RATIO[0] <= w / max(h, 1) <= ROUND_RATIO[1]:
            out.append((ox + int(cents[i][0]), oy + int(cents[i][1]), int(area)))
    return sorted(out, key=lambda b: -b[2])


def _masks(region: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bright = (s >= MIN_SAT) & (v >= MIN_VAL)
    red = bright & ((h <= RED_HUE[0]) | (h >= RED_HUE[1]))
    green = bright & (h >= GREEN_HUE[0]) & (h <= GREEN_HUE[1])
    return red, green


def _near_row(line: ocr.Line, blob: tuple[int, int, int], right_of: bool) -> bool:
    lx, ly = _center(line)
    bx, by, _ = blob
    same_row = abs(by - ly) <= ROW_TOL_LINES * line.h
    side = (bx > line.x + line.w) if right_of else (bx < line.x)
    return same_row and side and abs(bx - lx) <= NEAR_LINES * line.h


def _strip_lines(frame: np.ndarray, blob: tuple[int, int, int]) -> list[ocr.Line]:
    """OCR ampliado só da faixa à direita do X (onde fica a caixinha)."""
    bx, by, area = blob
    d = max(4, int(area ** 0.5))
    fh, fw = frame.shape[:2]
    x0, x1 = max(0, bx - d), min(fw, bx + int(STRIP_RIGHT_DIAMS * d))
    y0, y1 = max(0, by - int(STRIP_UP_DIAMS * d)), min(fh, by + int(STRIP_DOWN_DIAMS * d))
    strip = frame[y0:y1, x0:x1]
    if strip.size == 0:
        return []
    raw = ocr.read_lines(strip, min_height=STRIP_UPSCALE * strip.shape[0])
    return [ocr.Line(l.text, l.x + x0, l.y + y0, l.w, l.h) for l in raw]


def _list_under(pill: ocr.Line, lines: list[ocr.Line]) -> bool:
    """A lista de comandos está aberta embaixo DESTA caixinha? Palavras soltas na tela não
    contam: só itens na coluna dela, começando logo abaixo, 3+ na ordem da lista do jogo."""
    left = pill.x - LIST_COLUMN_WIDTHS * pill.w
    right = pill.x + pill.w + LIST_COLUMN_WIDTHS * pill.w
    items, seen = [], set()
    for line in sorted(lines, key=lambda l: l.y):
        word, cx = _squash(line.text), line.x + line.w // 2
        if word in COMMAND_WORDS and line.y > pill.y + pill.h and left <= cx <= right and word not in seen:
            items.append(line)
            seen.add(word)
    if len(items) < MIN_LIST_WORDS:
        return False
    if items[0].y - (pill.y + pill.h) > LIST_FIRST_GAP_LINES * pill.h:
        return False
    order = [COMMAND_ORDER.index(_squash(l.text)) for l in items]
    return order == sorted(order)


def classify(frame: np.ndarray | None) -> SpawnScreen:
    if frame is None or frame.size == 0:
        return SpawnScreen("unknown")
    fh, fw = frame.shape[:2]
    ox, oy = int(REGION_X[0] * fw), int(REGION_Y[0] * fh)
    region = frame[oy:int(REGION_Y[1] * fh), ox:int(REGION_X[1] * fw)]
    raw = ocr.read_lines(region, min_height=OCR_UPSCALE * region.shape[0])
    lines = [ocr.Line(l.text, l.x + ox, l.y + oy, l.w, l.h) for l in raw]
    red_mask, green_mask = _masks(region)
    reds, greens = _round_blobs(red_mask, ox, oy), _round_blobs(green_mask, ox, oy)
    for blob in reds[:STRIP_MAX_BLOBS]:
        lines += _strip_lines(frame, blob)
    for line in sorted(lines, key=lambda l: l.y):
        text = _squash(line.text)
        if not (text.endswith("command") or text == "set"):
            continue
        cancel = next((b for b in reds if _near_row(line, b, right_of=False)), None)
        if cancel is None:
            continue  # a caixinha de verdade tem o X vermelho na mesma linha
        # altura do clique vem do X (cor = posição exata); o OCR só dá o x da caixinha
        pill, cancel_pos = (_center(line)[0], cancel[1]), cancel[:2]
        if text == "set":
            ok = next((b for b in greens if _near_row(line, b, right_of=True)), None)
            if ok is None:
                return SpawnScreen("typed", pill_pos=pill, cancel_pos=cancel_pos)
            return SpawnScreen("confirm", pill_pos=pill, cancel_pos=cancel_pos, confirm_pos=ok[:2])
        kind = "list_open" if _list_under(line, lines) else "closed_box"
        return SpawnScreen(kind, pill_pos=pill, cancel_pos=cancel_pos)
    commands = next((l for l in lines if _squash(l.text) == "commands"), None)
    if commands is not None:
        return SpawnScreen("normal", commands_pos=_center(commands))
    return SpawnScreen("unknown")


class Setter:
    """Máquina de estados: a cada passo olha a tela e faz só o próximo passo seguro.

    `actions` precisa de grab() -> (origem_x, origem_y, frame), click(x, y) em pixels do
    frame, type_text(s), press(key), sleep(sec), now(), status(msg).
    """

    def __init__(self, actions, timeout_sec: float = TOTAL_TIMEOUT_SEC) -> None:
        self.a = actions
        self.timeout = timeout_sec

    def run(self) -> SpawnResult:
        a = self.a
        start = a.now()
        self._clicked: dict[str, float] = {}
        self._typed_at: float | None = None
        self._entered = self._confirmed = self._seen = False
        self._list_reads, self._last_read = 0, None
        s = SpawnScreen("unknown")
        kind_now, kind_since = None, start
        while a.now() - start < self.timeout:
            _, _, frame = a.grab()
            s = classify(frame)
            now = a.now()
            if self._last_read is not None and now - self._last_read > MAX_READ_GAP_SEC:
                self._list_reads = 0  # leitura atrasada: a caixinha pode ter perdido o foco
            self._last_read = now
            if s.kind != kind_now:
                kind_now, kind_since = s.kind, now
            self._list_reads = self._list_reads + 1 if s.kind == "list_open" else 0
            result = self._step(s, now, now - kind_since)
            if result is not None:
                return result
            a.sleep(POLL_SEC)
        return self._give_up(s, "tempo esgotado")

    def _step(self, s: SpawnScreen, now: float, same_for: float) -> SpawnResult | None:
        if s.kind == "unknown":
            if self._confirmed:
                return self._done()  # clicou no ✓ e a caixinha sumiu
            if not self._seen and same_for >= NO_BUTTON_SEC:
                return SpawnResult(False, "não achei o botão Commands")
            if self._seen and same_for >= STEP_TIMEOUT_SEC:
                return self._give_up(s, "a tela ficou irreconhecível")
            return None
        self._seen = True
        if same_for >= STEP_TIMEOUT_SEC:
            return self._give_up(s, i18n._("travou em '{kind}'", kind=s.kind))
        handler = getattr(self, f"_on_{s.kind}")
        return handler(s, now)

    def _on_normal(self, s: SpawnScreen, now: float) -> SpawnResult | None:
        if self._confirmed:
            return self._done()
        if self._typed_at is not None:
            return SpawnResult(False, "a caixinha fechou sem confirmar")
        self._click_once("normal", s.commands_pos, now)
        return None

    def _on_closed_box(self, s: SpawnScreen, now: float) -> SpawnResult | None:
        if self._typed_at is not None:
            return self._give_up(s, "o texto não entrou na caixinha")
        self._click_once("closed_box", s.pill_pos, now)
        return None

    def _on_list_open(self, s: SpawnScreen, now: float) -> SpawnResult | None:
        if self._typed_at is None:
            if "closed_box" not in self._clicked:
                return self._give_up(s, "a lista já estava aberta (não fui eu que abri)")
            if self._list_reads >= LIST_READS_TO_TYPE:
                self.a.status(i18n._("Setando o spawn: digitando 'set'."))
                self.a.type_text("set")  # lista aberta em leituras seguidas = caixinha ativa
                self._typed_at = now
        elif now - self._typed_at >= TYPE_CONFIRM_SEC:
            return self._give_up(s, "o texto não entrou na caixinha")
        return None

    def _on_typed(self, s: SpawnScreen, now: float) -> SpawnResult | None:
        if self._typed_at is None:
            return self._give_up(s, "a caixinha já tinha 'set' (não fui eu que digitei)")
        if not self._entered:
            self.a.press("enter")
            self._entered = True
        return None

    def _on_confirm(self, s: SpawnScreen, now: float) -> SpawnResult | None:
        if not self._entered:
            return self._give_up(s, "apareceu um ✓ sem eu ter digitado nada")
        if self._click_once("confirm", s.confirm_pos, now):
            self._confirmed = True
        return None

    def _click_once(self, key: str, pos: tuple[int, int] | None, now: float) -> bool:
        """Clica, mas não repete na mesma tela antes do intervalo mínimo."""
        if pos is None or now - self._clicked.get(key, -CLICK_COOLDOWN_SEC) < CLICK_COOLDOWN_SEC:
            return False
        self._clicked[key] = now
        return self.a.click(*pos) is not False  # clique que não saiu (mouse em uso) não conta

    def _done(self) -> SpawnResult:
        self.a.status(i18n._("Spawn setado no ponto de pesca."))
        return SpawnResult(True, "ok")

    def _give_up(self, s: SpawnScreen, reason: str) -> SpawnResult:
        """Desiste; fecha a caixinha só se o X estiver na tela AGORA (nunca clica onde ele estava)."""
        if s.cancel_pos is not None:
            self.a.click(*s.cancel_pos)
            reason = i18n._(reason)
        elif self._seen:
            reason = i18n._("{reason} (a caixinha pode ter ficado aberta)", reason=i18n._(reason))
        else:
            reason = i18n._(reason)
        self.a.status(i18n._("Não consegui setar o spawn: {reason}.", reason=reason))
        return SpawnResult(False, reason)
