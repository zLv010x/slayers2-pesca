"""O ciclo de pesca: conferir → lançar → minigame → segurar T → registrar.

Regras de segurança:
- Só clica/aperta teclas com o Roblox em primeiro plano (senão pausa e espera).
- Confere a vara na hotbar antes de lançar e aperta a tecla UMA vez por tentativa.
- Confere a bússola antes de lançar: câmera girada = pausa, não lança torto.
- Muitos lançamentos seguidos sem minigame = para e avisa (personagem caiu, etc.).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

import hotbar
import loot as loot_mod
import screen
import window
from bar_control import TrackController
from bar_detect import Detector
from compass import CompassLock
from session import Session
from webhook import DiscordNotifier, LootReport

SEARCH_PAD_X, SEARCH_PAD_X_MIN = 1.5, 80
SEARCH_PAD_Y, SEARCH_PAD_Y_MIN = 0.125, 24
START_HITS = 2
RELEASE_AFTER_LOST_SEC = 0.3
POPUP_POLL_SEC = 0.25
FOREGROUND_POLL_SEC = 0.5


class StopRun(Exception):
    """Pedido de parada (F1) ou problema que exige parar a macro."""


@dataclass
class Callbacks:
    status: Callable[[str], None]
    # (itens novos, recorte do último item para mostrar na tela); lista vazia = drop perdido
    loot: Callable[[list[loot_mod.Loot], np.ndarray | None], None]


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    w: int
    h: int


class Fisher:
    def __init__(self, cfg: dict, cb: Callbacks, session: Session,
                 notifier: DiscordNotifier, compass: CompassLock) -> None:
        self.cfg = cfg
        self.cb = cb
        self.session = session
        self.notifier = notifier
        self.compass = compass
        self.detector = Detector()
        self.tracker = TrackController()
        self.mouse = screen.MouseButton()
        self.grabber: screen.Grabber | None = None
        self.hwnd: int | None = None
        self._stop = threading.Event()
        self.failed_casts = 0

    # ---------- utilidades ----------
    def t(self, key: str) -> float:
        return float(self.cfg["timings"][key])

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise StopRun()

    def sleep(self, seconds: float) -> None:
        end = time.perf_counter() + max(0.0, seconds)
        while time.perf_counter() < end:
            self._check_stop()
            time.sleep(min(0.02, max(0.0, end - time.perf_counter())))

    def _problem(self, msg: str) -> None:
        """Para a macro e avisa no Discord."""
        if self.cfg["discord"].get("notify_problems", True):
            self.notifier.send_text(f"⚠️ Macro parou: {msg}", ping=True)
        raise StopRun(msg)

    def rect(self) -> window.Rect:
        """Área do jogo agora. Espera (pausado) enquanto o Roblox não estiver na frente."""
        warned = False
        while True:
            self._check_stop()
            if not self.hwnd or window.client_rect(self.hwnd) is None:
                self.hwnd = window.find_roblox()
            if self.hwnd is None:
                self.cb.status("Roblox não encontrado. Abra o jogo.")
            elif window.is_foreground(self.hwnd):
                r = window.client_rect(self.hwnd)
                if r is not None:
                    if warned:
                        self.cb.status("Roblox de volta, continuando...")
                    return r
            elif not warned:
                self.mouse.release()
                self.cb.status("Pausado: o Roblox não está na frente. Clique no jogo para continuar.")
                warned = True
            time.sleep(FOREGROUND_POLL_SEC)

    def frame(self) -> tuple[window.Rect, np.ndarray]:
        r = self.rect()
        return r, self.grabber.grab(r)

    @staticmethod
    def to_screen(r: window.Rect, fx: float, fy: float) -> tuple[int, int]:
        return int(round(r.x + fx * r.w)), int(round(r.y + fy * r.h))

    # ---------- etapas ----------
    def ensure_rod(self) -> None:
        key = str(self.cfg["rod_key"]).strip().lower()
        retries = int(self.cfg["limits"]["rod_retries"])
        for attempt in range(retries + 1):
            _, img = self.frame()
            if hotbar.check_rod(img).equipped:
                return
            if not key or attempt == retries:
                break
            self.cb.status(f"Vara fora da mão: apertando {key.upper()} ({attempt + 1}/{retries})...")
            screen.tap_key(key)
            self.sleep(self.t("rod_equip_wait_sec"))
        self._problem(f"não consegui equipar a vara (tecla {key.upper() or '?'}).")

    def check_camera(self) -> None:
        if not self.cfg.get("compass_lock", True) or not self.compass.ready:
            return
        tol = int(self.cfg.get("compass_tolerance_px", 6))
        while True:
            _, img = self.frame()
            drift = self.compass.drift_px(img)
            if drift is not None and abs(drift) <= tol:
                return
            msg = "bússola não encontrada" if drift is None else f"câmera girou {drift:+d}px"
            self.cb.status(f"Pausado: {msg}. Volte a câmera para a posição marcada (ou remarque com F2).")
            self.sleep(1.0)

    def cast(self) -> None:
        pt = self.cfg["cast_point"]
        r = self.rect()
        x, y = self.to_screen(r, pt["x"], pt["y"])
        self.cb.status("Lançando...")
        screen.click_at(x, y)
        self.sleep(self.t("after_cast_sec"))

    def _scan_rect(self, r: window.Rect) -> PixelRect:
        sa = self.cfg["scan_area"]
        return PixelRect(int(r.x + sa["x"] * r.w), int(r.y + sa["y"] * r.h),
                         max(1, int(sa["w"] * r.w)), max(1, int(sa["h"] * r.h)))

    @staticmethod
    def _search_rect(r: window.Rect, s: PixelRect) -> PixelRect:
        px = max(SEARCH_PAD_X_MIN, int(SEARCH_PAD_X * s.w))
        py = max(SEARCH_PAD_Y_MIN, int(SEARCH_PAD_Y * s.h))
        x0, y0 = max(r.x, s.x - px), max(r.y, s.y - py)
        x1, y1 = min(r.x + r.w, s.x + s.w + px), min(r.y + r.h, s.y + s.h + py)
        return PixelRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))

    def minigame(self) -> bool:
        """Joga o minigame. True = terminou (ir coletar); False = nem começou."""
        self.tracker.configure(self.cfg["tracking"])
        frame_budget = 1.0 / max(5.0, float(self.cfg["tracking"]["task_fps"]))
        start_deadline = time.perf_counter() + self.t("minigame_start_timeout_sec")
        end_deadline = time.perf_counter() + self.t("minigame_max_sec")
        lost_sec = self.t("ball_lost_sec")
        started, hits, last_game, near, last_seen = False, 0, None, None, 0.0
        self.mouse.release()
        self.cb.status("Esperando o peixe morder...")
        try:
            while True:
                t0 = time.perf_counter()
                r = self.rect()
                scan = self._scan_rect(r)
                search = self._search_rect(r, scan)
                img = self.grabber.grab(window.Rect(search.x, search.y, search.w, search.h))
                game = self.detector.find(img, (search.x, search.y), near)
                now = time.perf_counter()
                if game is not None and not started and not (
                    scan.x - game.ball_w <= game.ball_x <= scan.x + scan.w + game.ball_w
                ):
                    game = None
                if not started:
                    if game is not None and (last_game is None or abs(game.ball_x - last_game.ball_x) <= game.ball_w):
                        hits += 1
                        if hits >= START_HITS:
                            started, last_seen = True, now
                            near = (game.ball_x, game.ball_y)
                            self.tracker.start(game.ball_y, game.zone_y, game.ball_h, now)
                            end_deadline = now + self.t("minigame_max_sec")
                            self.cb.status("Minigame!")
                    else:
                        hits = 1 if game is not None else 0
                    last_game = game
                    if not started and now >= start_deadline:
                        return False
                else:
                    if game is None:
                        if now - last_seen > lost_sec:
                            return True
                        if now - last_seen > RELEASE_AFTER_LOST_SEC:
                            self.mouse.set(False)
                    else:
                        last_seen, near = now, (game.ball_x, game.ball_y)
                        self.tracker.observe(game.ball_y, game.ball_h, game.zone_top, game.zone_y, now)
                        self.mouse.set(bool(self.tracker.decide(now)))
                    if now >= end_deadline:
                        return True
                leftover = frame_budget - (time.perf_counter() - t0)
                if leftover > 0:
                    self.sleep(leftover)
                else:
                    self._check_stop()
        finally:
            self.mouse.release()

    def _poll_new(self, before: list[loot_mod.Loot], until: float
                  ) -> tuple[list[loot_mod.Loot], np.ndarray | None]:
        while time.perf_counter() < until:
            _, img = self.frame()
            fresh = loot_mod.new_items(before, loot_mod.read_popups(img))
            if fresh:
                return fresh, img
            self.sleep(POPUP_POLL_SEC)
        return [], None

    def collect(self) -> list[loot_mod.Loot]:
        self.sleep(self.t("after_minigame_sec"))
        # Avisos de pescas anteriores ainda na tela não podem ser contados de novo.
        _, img = self.frame()
        before = loot_mod.read_popups(img)
        self.cb.status("Segurando T para pegar...")
        screen.press_key("t")
        try:
            fresh, img = self._poll_new(before, time.perf_counter() + self.t("collect_hold_sec"))
        finally:
            screen.release_key("t")
        if not fresh:
            fresh, img = self._poll_new(before, time.perf_counter() + self.t("popup_wait_sec"))
        for item in fresh:
            self._report(item, img)
        if not fresh:
            self.session.record_miss()
        snap = loot_mod.item_snapshot(img, fresh[-1]) if fresh else None
        self.cb.loot(fresh, snap)
        self.sleep(self.t("after_collect_sec"))
        return fresh

    def _report(self, item: loot_mod.Loot, img: np.ndarray) -> None:
        self.session.record(item.name, item.quantity, item.rarity)
        d = self.cfg["discord"]
        tracked = str(d.get("tracked_item", "")).strip()
        self.notifier.send_loot(LootReport(
            name=item.name,
            quantity=item.quantity,
            rarity=item.rarity,
            session_count=self.session.catches,
            item_total=self.session.total_of(item.name),
            tracked_name=tracked,
            tracked_total=self.session.total_of(tracked) if tracked else 0,
            elapsed=self.session.elapsed_text(),
            image=loot_mod.item_snapshot(img, item) if d.get("send_image", True) else None,
            is_new=item.is_new,
        ))

    # ---------- laço ----------
    def one_cycle(self) -> None:
        self.ensure_rod()
        self.check_camera()
        self.cast()
        if not self.minigame():
            self.failed_casts += 1
            limit = int(self.cfg["limits"]["max_failed_casts"])
            self.cb.status(f"Nenhum peixe mordeu ({self.failed_casts}/{limit}). Tentando de novo...")
            if self.failed_casts >= limit:
                self._problem(f"{limit} lançamentos seguidos sem minigame (caiu na água? vara presa?).")
            return
        self.failed_casts = 0
        self.collect()

    def run(self, stop: threading.Event) -> str:
        """Roda até parar. Devolve o motivo da parada."""
        self._stop = stop
        if not self.cfg.get("cast_point"):
            return "Marque o ponto de lançamento primeiro (F2)."
        self.hwnd = window.find_roblox()
        if self.hwnd is None:
            return "Roblox não encontrado. Abra o jogo."
        window.focus(self.hwnd)
        self.grabber = screen.Grabber()
        try:
            while True:
                self.one_cycle()
        except StopRun as exc:
            return str(exc) or "Parado."
        finally:
            self.mouse.release()
            screen.release_key("t")
            self.grabber.close()
