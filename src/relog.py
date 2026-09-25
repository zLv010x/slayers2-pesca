"""Reconecta sozinho quando o servidor cai: Disconnected -> Reconnect -> menu
principal -> PLAY -> seleção de servidor -> JOIN -> de volta ao jogo.

O texto e o código do dialog "Disconnected" mudam (inatividade, internet, servidor
desligado...), então a detecção é genérica: só olha o título "Disconnected" e o
botão "Reconnect". Alguns códigos (ex.: 264, conta entrou de outro aparelho) não
podem reconectar sozinhos — derrubariam quem está jogando de verdade — e um dialog
sem botão Reconnect também não: nesses casos só avisamos.

`classify()` lê a tela e diz que tela é (com as posições úteis em pixels do frame).
`Relogger` é a máquina de estados: a cada passo ela olha a tela de novo (nunca
assume ordem fixa) e decide o que fazer, com timeout por etapa e no total.

Interface de `actions` que o integrador precisa ligar (nenhuma delas existe hoje
em screen.py — são as únicas coisas novas que este módulo precisa receber):
    grab() -> (origem_x, origem_y, frame)      # print da área do jogo
    click(x, y)                                 # clique simples (screen.click_at)
    mouse_down(x, y)                            # move até lá e segura o botão
    mouse_up()                                   # solta o botão (mesmo se já solto)
    type_text(text)                             # screen.type_text
    press(key)                                   # ex.: "enter" (screen.tap_key)
    sleep(sec)                                   # espera interrompível
    now() -> float                               # relógio (time.monotonic)
    in_game(frame) -> bool                       # confirma que voltou pro jogo (hotbar etc.)
    status(msg)                                  # loga/mostra o que está acontecendo
`mouse_down`/`mouse_up` existem à parte de `click` porque segurar o JOIN precisa
soltar cedo se a tela mudar (ou se der exceção) — um `hold(x, y, sec)` bloqueado
não permite isso.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

import i18n
import menu
import ocr

DEFAULTS: dict = {
    "enabled": False,
    "has_spawn_gamepass": False,  # reservado p/ funcionalidade futura (não usado aqui)
    "spawn_set": False,            # idem
    "server_mode": "vip",          # "vip" (servidor próprio) | "nick" (entra no de outro)
    "owner_nick": "",
    "map_name": "Ouwland",
    "hold_join_sec": 3.0,  # limite: solta assim que começa a carregar (leva < 1 s)
    "step_timeout_sec": 90,
    "total_timeout_sec": 600,
    "no_reconnect_codes": [264],
    # quanto tempo "sem tela conhecida" (unknown) até considerar que já voltou ao
    # jogo, mesmo sem in_game() confirmar (cobre chamar o relog com o jogo já normal)
    "settle_sec": 8.0,
}

# --- calibração das posições/textos, ver tests/fixtures/relog_*.webp ---------
ERROR_CODE_RE = re.compile(r"error\s*code\D{0,4}(\d+)", re.IGNORECASE)
JOIN_PRIVATE_WORDS = {"join", "private"}  # texto do botão do modo nick, ainda sem print p/ confirmar
LOADING_WORD = "entering"
# card do servidor fica abaixo-direita do nome do mapa (fração do tamanho do frame)
CARD_OFFSET_X_FRAC = 0.075
CARD_OFFSET_Y_FRAC = 0.230
# "Private server owner" o OCR lê embaralhado (fonte clara/itálica): a posição vem
# por deslocamento a partir do botão JOIN, que o OCR lê bem.
OWNER_FIELD_DY_FRAC = 0.052
# margem ao redor do dialog Disconnected pra separar a mensagem de texto de fundo
DIALOG_PAD_X_FRAC = 0.09
DIALOG_PAD_Y_FRAC = 0.05

# janelas pequenas: o OCR da tela inteira não lê texto pequeno. Além dele, sempre
# fazemos OCR de dois recortes ampliados 4x e somamos a origem de volta ao frame.
DIALOG_CROP_X = (0.25, 0.75)
DIALOG_CROP_Y = (0.30, 0.70)
LOADING_CROP_X = (0.30, 0.70)
LOADING_CROP_Y = (0.70, 0.95)
CROP_UPSCALE = 4

# fallback do botão Reconnect por cor quando o OCR não lê o texto do botão: ele é
# o único retângulo branco CHEIO logo abaixo do título (o Leave só tem contorno).
RECONNECT_MIN_CHANNEL = 225  # mínimo dos 3 canais (BGR) pra contar como "branco"
RECONNECT_MIN_ASPECT = 2.5   # largura / altura mínima de um botão
RECONNECT_MIN_AREA_PX = 50   # ignora ruído (letras do título também são claras)

# clicar de novo na mesma tela antes desse tempo é desperdício (ou pior: cai já na
# tela seguinte, ex.: um 2º clique no PLAY cair no painel de amigos do próximo menu)
CLICK_COOLDOWN_SEC = 5.0

POLL_SEC = 0.5       # intervalo entre olhadas na tela
HOLD_POLL_SEC = 0.1  # intervalo de checagem durante o JOIN segurado


@dataclass(frozen=True)
class Screen:
    """O que `classify()` enxergou: tipo da tela + posições úteis (pixels do frame)."""
    kind: str  # "disconnected" | "main_menu" | "server_select" | "server_card" | "loading" | "game_loading" | "unknown"
    message: str | None = None
    error_code: int | None = None
    reconnect_pos: tuple[int, int] | None = None
    leave_pos: tuple[int, int] | None = None
    play_pos: tuple[int, int] | None = None
    card_pos: tuple[int, int] | None = None
    owner_field_pos: tuple[int, int] | None = None
    join_pos: tuple[int, int] | None = None
    join_private_pos: tuple[int, int] | None = None
    skip_pos: tuple[int, int] | None = None   # botão "Skip loading!" da tela de carregamento do jogo


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _squash(text: str) -> str:
    """Texto em minúsculas sem espaços: o OCR às vezes divide "Reconnect" em duas."""
    return re.sub(r"\s+", "", text.lower())


def _center(line: ocr.Line) -> tuple[int, int]:
    return (line.x + line.w // 2, line.y + line.h // 2)


def classify(frame: np.ndarray | None, cfg: dict | None = None) -> Screen:
    """Descobre em qual tela de reconexão o jogo está agora ("unknown" se for outra)."""
    if frame is None or frame.size == 0:
        return Screen(kind="unknown")
    cfg = cfg or {}
    lines = ocr.read_lines(frame)
    lines += _crop_lines(frame, DIALOG_CROP_X, DIALOG_CROP_Y)
    lines += _crop_lines(frame, LOADING_CROP_X, LOADING_CROP_Y)
    return (
        _detect_disconnected(frame, lines)
        or _detect_main_menu(frame)
        or _detect_game_loading(lines)
        or _detect_loading(lines)
        or _detect_server(frame, lines, cfg.get("map_name", DEFAULTS["map_name"]))
        or Screen(kind="unknown")
    )


def _crop_lines(frame: np.ndarray, x_range: tuple[float, float],
                 y_range: tuple[float, float]) -> list[ocr.Line]:
    """OCR de um recorte ampliado 4x (janela pequena = texto pequeno demais pro OCR
    ler na tela inteira), com as coordenadas já somadas de volta pro frame."""
    fh, fw = frame.shape[:2]
    x0, x1 = int(x_range[0] * fw), int(x_range[1] * fw)
    y0, y1 = int(y_range[0] * fh), int(y_range[1] * fh)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    lines = ocr.read_lines(crop, min_height=CROP_UPSCALE * crop.shape[0])
    return [ocr.Line(l.text, l.x + x0, l.y + y0, l.w, l.h) for l in lines]


def _bbox(frame: np.ndarray, lines: list[ocr.Line]) -> tuple[float, float, float, float]:
    fh, fw = frame.shape[:2]
    x0 = min(l.x for l in lines) - DIALOG_PAD_X_FRAC * fw
    y0 = min(l.y for l in lines) - DIALOG_PAD_Y_FRAC * fh
    x1 = max(l.x + l.w for l in lines) + DIALOG_PAD_X_FRAC * fw
    y1 = max(l.y + l.h for l in lines) + DIALOG_PAD_Y_FRAC * fh
    return x0, y0, x1, y1


def _inside(line: ocr.Line, box: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = box
    cx, cy = _center(line)
    return x0 <= cx <= x1 and y0 <= cy <= y1


def _detect_disconnected(frame: np.ndarray, lines: list[ocr.Line]) -> Screen | None:
    # título tolerante: em janela pequena o OCR só pega parte de "Disconnected"
    title = next((l for l in lines if "disconnect" in _squash(l.text)), None)
    reconnect = next((l for l in lines if _squash(l.text) == "reconnect"), None)
    if title is None and reconnect is None:
        return None
    leave = next((l for l in lines if _squash(l.text) == "leave"), None)
    anchors = [l for l in (title, reconnect, leave) if l is not None]
    box = _bbox(frame, anchors)
    error_code, message_parts = None, []
    for line in lines:
        if line in anchors or not _inside(line, box):
            continue
        match = ERROR_CODE_RE.search(line.text)
        if match:
            error_code = int(match.group(1))
        else:
            message_parts.append(line.text)
    reconnect_pos = _center(reconnect) if reconnect else None
    if reconnect_pos is None and title is not None:
        reconnect_pos = _find_reconnect_by_color(frame, title)
    return Screen(
        kind="disconnected",
        message=" ".join(message_parts) or None,
        error_code=error_code,
        reconnect_pos=reconnect_pos,
        leave_pos=_center(leave) if leave else None,
    )


def _find_reconnect_by_color(frame: np.ndarray, title: ocr.Line) -> tuple[int, int] | None:
    """Fallback quando o OCR não lê "Reconnect": procura, dentro do recorte do
    dialog e abaixo do título, o maior retângulo quase-branco cheio (o Leave é
    escuro só com contorno, então não entra nesse filtro)."""
    fh, fw = frame.shape[:2]
    x0, x1 = int(DIALOG_CROP_X[0] * fw), int(DIALOG_CROP_X[1] * fw)
    y0, y1 = int(DIALOG_CROP_Y[0] * fh), int(DIALOG_CROP_Y[1] * fh)
    crop = frame[y0:y1, x0:x1]
    y_from = title.y - y0
    if crop.size == 0 or not (0 <= y_from < crop.shape[0]):
        return None
    sub = crop[y_from:, :]
    mask = (np.min(sub, axis=2) >= RECONNECT_MIN_CHANNEL).astype(np.uint8)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best_area, best_center = 0, None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h == 0 or area < RECONNECT_MIN_AREA_PX or w / h < RECONNECT_MIN_ASPECT:
            continue
        if area > best_area:
            best_area, best_center = area, centroids[i]
    if best_center is None:
        return None
    cx, cy = best_center
    return (x0 + int(cx), y0 + y_from + int(cy))


def _detect_main_menu(frame: np.ndarray) -> Screen | None:
    """Mesma região/heurística de menu.is_main_menu, só que também acha o PLAY."""
    region, ox, oy = menu.menu_region(frame)
    if region.size == 0:
        return None
    found = menu.find_menu_words(region)
    if not menu.looks_like_menu(found):  # 3 de 4 na ordem: o PLAY fica na área da party
        return None
    play = found.get("play")
    play_pos = (ox + play.x + play.w // 2, oy + play.y + play.h // 2) if play else None
    return Screen(kind="main_menu", play_pos=play_pos)


def _detect_game_loading(lines: list[ocr.Line]) -> Screen | None:
    """Carregamento do jogo depois de entrar ("Loading 85 / 189 Assets.." + botão "Skip loading!")."""
    skip = next((l for l in lines if "skip" in _squash(l.text)), None)
    assets = any("assets" in _squash(l.text) for l in lines)
    if skip is None and not assets:
        return None
    return Screen(kind="game_loading", skip_pos=_center(skip) if skip is not None else None)


def _detect_loading(lines: list[ocr.Line]) -> Screen | None:
    # em janela pequena "Now Entering..." sai torto (ex.: "owentermg", "owentenng")
    for l in lines:
        squashed = _squash(l.text)
        if LOADING_WORD in squashed or "owent" in squashed:
            return Screen(kind="loading")
    return None


def _detect_server(frame: np.ndarray, lines: list[ocr.Line], map_name: str) -> Screen | None:
    fh, fw = frame.shape[:2]
    join = next((l for l in lines if _words(l.text) == {"join"}), None)
    if join:
        jx, jy = _center(join)
        owner_pos = (jx, int(jy - OWNER_FIELD_DY_FRAC * fh))
        return Screen(kind="server_card", join_pos=(jx, jy), owner_field_pos=owner_pos,
                      join_private_pos=_find_join_private(lines))
    title = next((l for l in lines if map_name.lower() in _words(l.text)), None)
    if title:
        card_pos = (title.x + int(CARD_OFFSET_X_FRAC * fw), title.y + int(CARD_OFFSET_Y_FRAC * fh))
        return Screen(kind="server_select", card_pos=card_pos)
    return None


def _find_join_private(lines: list[ocr.Line]) -> tuple[int, int] | None:
    """Botão do modo nick (texto ainda não confirmado): "join"+"private" numa linha
    curta, sem "hold" (isso já é a legenda "Hold to join private server", sempre visível)."""
    for line in lines:
        words = _words(line.text)
        if JOIN_PRIVATE_WORDS <= words and "hold" not in words and len(words) <= 3:
            return _center(line)
    return None


@dataclass(frozen=True)
class RelogResult:
    ok: bool
    reason: str
    error_code: int | None = None

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class Relogger:
    """Máquina de estados do relog. Ver docstring do módulo p/ interface de `actions`."""
    cfg: dict
    actions: Any
    _typed_nick: bool = field(default=False, init=False, repr=False)
    _unknown_since: float | None = field(default=None, init=False, repr=False)
    _click_times: dict = field(default_factory=dict, init=False, repr=False)

    def run(self) -> RelogResult:
        cfg = self.cfg
        if not cfg.get("enabled", False):
            return RelogResult(False, "desabilitado")
        if cfg.get("server_mode") not in ("vip", "nick"):
            return RelogResult(False, "modo_servidor_invalido")
        self._typed_nick = False
        self._unknown_since = None
        self._click_times = {}
        a = self.actions
        total_deadline = a.now() + cfg.get("total_timeout_sec", DEFAULTS["total_timeout_sec"])
        step_timeout = cfg.get("step_timeout_sec", DEFAULTS["step_timeout_sec"])
        last_kind, step_deadline = None, a.now() + step_timeout
        while True:
            now = a.now()
            if now >= total_deadline:
                a.status(i18n._("Reconexão automática: tempo total esgotado."))
                return RelogResult(False, "timeout_total")
            _, _, frame = a.grab()
            screen = classify(frame, cfg)
            if screen.kind != last_kind:
                last_kind, step_deadline, self._typed_nick = screen.kind, now + step_timeout, False
                if screen.kind != "unknown":
                    self._unknown_since = None
            elif now >= step_deadline:
                a.status(i18n._("Reconexão automática: travou em '{kind}'.", kind=screen.kind))
                return RelogResult(False, "timeout_etapa")
            result = self._step(screen, frame)
            if result is not None:
                return result
            a.sleep(POLL_SEC)

    def _throttled_click(self, kind: str, x: int, y: int) -> None:
        """Não clica de novo na mesma tela antes de CLICK_COOLDOWN_SEC (ver constante)."""
        now = self.actions.now()
        last = self._click_times.get(kind)
        if last is not None and now - last < CLICK_COOLDOWN_SEC:
            return
        self._click_times[kind] = now
        self.actions.click(x, y)

    def _step(self, screen: Screen, frame: np.ndarray) -> RelogResult | None:
        handlers = {
            "disconnected": self._on_disconnected,
            "main_menu": self._on_main_menu,
            "server_select": self._on_server_select,
            "server_card": self._on_server_card,
            "loading": self._on_loading,
            "game_loading": self._on_game_loading,
        }
        return handlers.get(screen.kind, self._on_unknown)(screen, frame)

    def _on_disconnected(self, screen: Screen, frame: np.ndarray) -> RelogResult | None:
        no_reconnect = self.cfg.get("no_reconnect_codes", DEFAULTS["no_reconnect_codes"])
        if screen.error_code in no_reconnect:
            self.actions.status(i18n._("Desconectado (código {code}): não reconecto sozinho.",
                                 code=screen.error_code))
            return RelogResult(False, "codigo_sem_reconexao", screen.error_code)
        if screen.reconnect_pos is None:
            self.actions.status(i18n._("Desconectado sem botão Reconnect: avisando."))
            return RelogResult(False, "sem_botao_reconnect", screen.error_code)
        self.actions.status(i18n._("Desconectado: clicando em Reconnect."))
        self._throttled_click("disconnected", *screen.reconnect_pos)
        return None

    def _on_main_menu(self, screen: Screen, frame: np.ndarray) -> None:
        if screen.play_pos:
            self.actions.status(i18n._("Menu principal: clicando em PLAY."))
            self._throttled_click("main_menu", *screen.play_pos)

    def _on_server_select(self, screen: Screen, frame: np.ndarray) -> None:
        if screen.card_pos:
            map_name = self.cfg.get("map_name", DEFAULTS["map_name"])
            self.actions.status(i18n._("Selecionando o servidor {map_name}.", map_name=map_name))
            self._throttled_click("server_select", *screen.card_pos)

    def _on_server_card(self, screen: Screen, frame: np.ndarray) -> None:
        if self.cfg.get("server_mode") == "vip":
            self._join_vip(screen, frame)
        else:
            self._join_nick(screen)

    def _on_loading(self, screen: Screen, frame: np.ndarray) -> None:
        self.actions.status(i18n._("Carregando..."))

    def _on_game_loading(self, screen: Screen, frame: np.ndarray) -> None:
        """Carregando o jogo: clica em "Skip loading!" (de novo só depois do intervalo) e espera."""
        self.actions.status(i18n._("Carregando o jogo: clicando em Skip loading."))
        if screen.skip_pos:
            self._throttled_click("game_loading", *screen.skip_pos)

    def _on_unknown(self, screen: Screen, frame: np.ndarray) -> RelogResult | None:
        if self.actions.in_game(frame):
            self.actions.status(i18n._("De volta ao jogo."))
            return RelogResult(True, "ok")
        # sem confirmação: se já não é nenhuma tela conhecida há tempo suficiente,
        # considera que voltou (cobre chamar o relog com o jogo já normal)
        now = self.actions.now()
        if self._unknown_since is None:
            self._unknown_since = now
        settle = self.cfg.get("settle_sec", DEFAULTS["settle_sec"])
        if now - self._unknown_since >= settle:
            self.actions.status(i18n._("De volta ao jogo (tela normal por tempo suficiente)."))
            return RelogResult(True, "ok")
        return None

    def _join_vip(self, screen: Screen, frame: np.ndarray) -> None:
        """Com VIP é só segurar o JOIN (o mundo já foi clicado): no meio da segurada ele
        vira "JOIN PRIVATE" e entra no servidor privado da pessoa."""
        if not screen.join_pos:
            return
        self.actions.status(i18n._("Servidor VIP: segurando o JOIN."))
        self._hold_join(*screen.join_pos)

    def _join_nick(self, screen: Screen) -> None:
        a = self.actions
        if not self._typed_nick:
            if not screen.owner_field_pos:
                return
            nick = self.cfg.get("owner_nick", "")
            a.status(i18n._("Servidor por nick: digitando '{nick}'.", nick=nick))
            a.click(*screen.owner_field_pos)
            a.type_text(nick)
            a.press("enter")
            self._typed_nick = True
        elif screen.join_private_pos:
            a.status(i18n._("Clicando em Join Private."))
            a.click(*screen.join_private_pos)

    def _hold_join(self, x: int, y: int) -> None:
        """Segura o JOIN até começar a carregar (ou até o limite). NÃO solta quando a tela
        "muda": o botão vira JOIN PRIVATE no meio da segurada e soltar ali cancela a entrada.
        Sempre solta no final, mesmo se algo der exceção no meio do caminho."""
        a = self.actions
        if a.mouse_down(x, y) is False:
            return  # o cursor não chegou no JOIN: não segura o botão em outro lugar
        try:
            deadline = a.now() + self.cfg.get("hold_join_sec", DEFAULTS["hold_join_sec"])
            while a.now() < deadline:
                a.sleep(HOLD_POLL_SEC)
                _, _, frame = a.grab()
                if classify(frame, self.cfg).kind == "loading":
                    break
        finally:
            a.mouse_up()
