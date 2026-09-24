"""O ciclo de pesca: conferir → lançar → minigame → segurar T → registrar.

Regras de segurança:
- Só clica/aperta teclas com o Roblox em primeiro plano (senão pausa e espera).
- Confere a vara na hotbar antes de lançar e aperta a tecla UMA vez por tentativa.
- Confere a bússola antes de lançar: câmera girada = pausa, não lança torto.
- Muitos lançamentos seguidos sem minigame = avisa, espera e tenta de novo.
- Qualquer problema vira "recuperação" (log + print + Discord + espera) em vez de
  parar: a ideia é rodar a noite toda. Só para de vez depois de muitas falhas seguidas.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

import bait_menu
import hotbar
import logbook
import loot as loot_mod
import prompt as prompt_mod
import screen
import window
from bar_control import TrackController
from bar_detect import Detector
from baits import BaitState
from catalog import Catalog
from compass import CompassLock
from session import Session
from webhook import DiscordNotifier, LootReport

SEARCH_PAD_X, SEARCH_PAD_X_MIN = 1.5, 80
SEARCH_PAD_Y, SEARCH_PAD_Y_MIN = 0.125, 24
START_HITS = 2
RELEASE_AFTER_LOST_SEC = 0.3
POPUP_POLL_SEC = 0.25
COLLECT_POLL_SEC = 0.05
# Aviso de coleta sumido por mais que isso = o jogo zerou o progresso do T.
# (um ou dois quadros sem achar o aviso não soltam o T à toa)
PROMPT_LOST_SEC = 0.6
PROMPT_LOST_CHECKS = 3
# Se o aviso nunca aparecer nesse tempo, segura T "no escuro" (como a versão antiga).
PROMPT_GRACE_SEC = 1.0
HOLD_SLACK_SEC = 1.5
# Pedido do usuário: segurar T sempre pelo menos isso (o jogo pede ~2,3 s).
MIN_T_HOLD_SEC = 3.25
FOREGROUND_POLL_SEC = 0.5
STATS_EVERY_CYCLES = 10
# Conferência de iscas que falhou: tenta de novo depois de tantos ciclos.
BAIT_RETRY_CYCLES = 20

log = logbook.get()


class StopRun(Exception):
    """Pedido de parada (F1) ou problema que exige parar a macro."""


class Recoverable(Exception):
    """Algo deu errado neste ciclo; dá para esperar e tentar de novo."""

    def __init__(self, msg: str, img: np.ndarray | None = None) -> None:
        super().__init__(msg)
        self.img = img


@dataclass
class Callbacks:
    status: Callable[[str], None]
    # (itens novos, recorte do último item para mostrar na tela); lista vazia = drop perdido
    loot: Callable[[list[loot_mod.Loot], np.ndarray | None], None]
    # (resumo das iscas, é aviso?)
    bait: Callable[[str, bool], None] = field(default=lambda text, warn: None)


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    w: int
    h: int


class Fisher:
    def __init__(self, cfg: dict, cb: Callbacks, session: Session,
                 notifier: DiscordNotifier, compass: CompassLock,
                 catalog: Catalog | None = None, baits: BaitState | None = None,
                 bait_path: Path | None = None) -> None:
        self.catalog = catalog
        self.baits = baits
        self.bait_path = bait_path
        self.bait_check_requested = False
        self._bait_retry_at = 0
        self._no_bait_warned = False
        self._menu_stuck = False
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
        self.recoveries = 0
        self.cycles = 0
        self._last_status = ""
        self._status_cb = cb.status
        cb.status = self._status

    def _status(self, msg: str) -> None:
        if msg != self._last_status:
            log.info(msg)
            self._last_status = msg
        self._status_cb(msg)

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

    def _notify(self, text: str, ping: bool = True) -> None:
        if self.cfg["discord"].get("notify_problems", True):
            self.notifier.send_text(text, ping=ping)

    def rect(self) -> window.Rect:
        """Área do jogo agora. Espera (pausado) enquanto o Roblox não estiver na frente."""
        warned, since = False, 0.0
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
            else:
                if not warned:
                    self.mouse.release()
                    self.cb.status("Pausado: o Roblox não está na frente. Clique no jogo para continuar.")
                    warned, since = True, time.perf_counter()
                refocus = self.t("refocus_after_sec")
                if refocus > 0 and time.perf_counter() - since >= refocus:
                    log.warning("Roblox fora da frente há %.0fs: trazendo de volta.", refocus)
                    window.focus(self.hwnd)
                    since = time.perf_counter()
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
        img = None
        for attempt in range(retries + 1):
            _, img = self.frame()
            check = hotbar.check_rod(img)
            log.debug("Vara: equipada=%s (slot 3 %.0f, vizinhos %.0f)",
                      check.equipped, check.inner_gray, check.outer_gray)
            if check.equipped:
                return
            if not key or attempt == retries:
                break
            self.cb.status(f"Vara fora da mão: apertando {key.upper()} ({attempt + 1}/{retries})...")
            screen.tap_key(key)
            self.sleep(self.t("rod_equip_wait_sec"))
        raise Recoverable(f"não consegui equipar a vara (tecla {key.upper() or '?'})", img)

    def check_camera(self) -> None:
        if not self.cfg.get("compass_lock", True) or not self.compass.ready:
            return
        tol = int(self.cfg.get("compass_tolerance_px", 6))
        paused_at, notified = None, False
        while True:
            _, img = self.frame()
            drift = self.compass.drift_px(img)
            if drift is not None and abs(drift) <= tol:
                if paused_at is not None:
                    log.info("Câmera voltou para a posição (desvio %+dpx).", drift)
                return
            msg = "bússola não encontrada" if drift is None else f"câmera girou {drift:+d}px"
            if paused_at is None:
                paused_at = time.perf_counter()
                logbook.save_evidence(img, "camera " + msg)
            elif not notified and time.perf_counter() - paused_at >= self.t("recovery_wait_sec"):
                self._notify(f"⏸️ Pesca pausada: {msg}. Arrume a câmera no jogo para continuar.")
                notified = True
            self.cb.status(f"Pausado: {msg}. Volte a câmera para a posição marcada (ou remarque o ponto).")
            self.sleep(1.0)

    def cast(self) -> None:
        pt = self.cfg["cast_point"]
        r = self.rect()
        x, y = self.to_screen(r, pt["x"], pt["y"])
        self.cb.status("Lançando...")
        log.debug("Clique de lançamento em (%d, %d) na janela %dx%d", x, y, r.w, r.h)
        if not screen.click_at(x, y):
            raise Recoverable(f"o mouse não chegou no ponto de lançamento ({x}, {y})", self._safe_shot())
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
                            waited = now - (start_deadline - self.t("minigame_start_timeout_sec"))
                            log.info("Peixe mordeu após %.1fs (quadrado %dpx)", waited, game.ball_h)
                            self.cb.status("Minigame!")
                    else:
                        hits = 1 if game is not None else 0
                    last_game = game
                    if not started and now >= start_deadline:
                        logbook.save_evidence(self.grabber.grab(r), "sem minigame")
                        return False
                else:
                    if game is None:
                        if now - last_seen > lost_sec:
                            log.info("Minigame terminou (%.1fs)",
                                     now - (end_deadline - self.t("minigame_max_sec")))
                            return True
                        if now - last_seen > RELEASE_AFTER_LOST_SEC:
                            self.mouse.set(False)
                    else:
                        last_seen, near = now, (game.ball_x, game.ball_y)
                        self.tracker.observe(game.ball_y, game.ball_h, game.zone_top, game.zone_y, now)
                        self.mouse.set(bool(self.tracker.decide(now)))
                    if now >= end_deadline:
                        log.warning("Minigame passou do tempo máximo: indo coletar mesmo assim.")
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

    def _hold_t(self, before: list[loot_mod.Loot], budget: float, where: str
                ) -> tuple[list[loot_mod.Loot], np.ndarray | None]:
        """Segura T acompanhando o aviso de coleta do jogo.

        Se o item balança, o aviso some e volta, e o jogo zera o progresso: então
        solta o T quando o aviso some e aperta de novo quando ele volta. Se o aviso
        nunca for detectado, segura "no escuro" (como antes) para não travar.
        """
        hold_need = max(self.t("collect_hold_sec"), MIN_T_HOLD_SEC)
        start = time.perf_counter()
        deadline = start + budget
        holding, hold_since, last_seen, seen_any, restarts = False, 0.0, -1.0, False, 0
        misses, polls = 0, 0
        self.cb.status(f"Segurando T para pegar ({where})...")
        try:
            while time.perf_counter() < deadline:
                _, img = self.frame()
                # leitura rápida (uma variante por vez, alternando); achou algo → confere com todas
                variant = loot_mod.OCR_VARIANTS[polls % len(loot_mod.OCR_VARIANTS)]
                polls += 1
                quick = loot_mod.read_popups(img, variants=(variant,), best=False)
                fresh = loot_mod.new_items(before, loot_mod.read_popups(img)) if quick else []
                if fresh:
                    if restarts:
                        log.info("Item pego %s depois de %d recomeço(s) do T.", where, restarts)
                    return fresh, img
                now = time.perf_counter()
                if prompt_mod.find_collect_prompt(img) is not None:
                    seen_any, last_seen, misses = True, now, 0
                else:
                    misses += 1
                # só considera que o aviso sumiu de verdade depois de várias checagens seguidas
                lost = misses >= PROMPT_LOST_CHECKS and now - last_seen >= PROMPT_LOST_SEC
                prompt_on = seen_any and not lost
                blind = not seen_any and now - start >= PROMPT_GRACE_SEC
                want = prompt_on or blind
                held = now - hold_since
                # Depois de apertar, segura pelo menos o tempo que o jogo pede: com a câmera longe o
                # aviso vira um losango pequeno que o detector perde, mas ele continua na tela.
                # Só então solta se o aviso sumiu (item balançou) ou se passou do tempo sem vir nada.
                if holding and ((not want and held >= hold_need) or held > hold_need + HOLD_SLACK_SEC):
                    screen.release_key("t")
                    holding = False
                    restarts += 1
                    log.debug("T solto %s (aviso na tela=%s, segurando há %.1fs)",
                              where, prompt_on, held)
                elif want and not holding:
                    screen.press_key("t")
                    holding, hold_since = True, now
                self.sleep(COLLECT_POLL_SEC)
        finally:
            screen.release_key("t")
        log.warning("Não pegou %s em %.0fs (aviso de coleta visto=%s, T recomeçado %d vez(es)).",
                    where, budget, seen_any, restarts)
        return self._poll_new(before, time.perf_counter() + self.t("popup_wait_sec"))

    def _drop_rod(self) -> None:
        """Guarda a vara para o item cair no chão (a vara volta sozinha no próximo ciclo)."""
        key = str(self.cfg["rod_key"]).strip().lower()
        if not key:
            return
        self.cb.status(f"Item não veio da vara: guardando a vara ({key.upper()}) para pegar do chão...")
        screen.tap_key(key)
        self.sleep(self.t("rod_equip_wait_sec"))
        _, img = self.frame()
        log.info("Vara guardada para pegar do chão (vara na mão agora=%s)", hotbar.check_rod(img).equipped)

    def collect(self) -> list[loot_mod.Loot]:
        self.sleep(self.t("after_minigame_sec"))
        # Avisos de pescas anteriores ainda na tela não podem ser contados de novo.
        _, img = self.frame()
        before = loot_mod.read_popups(img)
        fresh, img = self._hold_t(before, self.t("collect_timeout_sec"), "da vara")
        if not fresh and self.cfg.get("ground_pickup", True):
            self._drop_rod()
            fresh, img = self._hold_t(before, self.t("ground_pickup_sec"), "do chão")
            if fresh:
                log.info("Item recuperado do chão.")
        if before:
            log.debug("Avisos antigos ainda na tela: %s", [f"{i.name} x{i.quantity}" for i in before])
        fresh = [self._report(item, img) for item in fresh]
        if not fresh:
            self.session.record_miss()
            log.warning("Nenhum aviso de item depois do T (drop perdido ou aviso não lido).")
            _, shot = self.frame()
            logbook.save_evidence(shot, "sem aviso de item")
        snap = loot_mod.item_snapshot(img, fresh[-1]) if fresh else None
        self.cb.loot(fresh, snap)
        self.sleep(self.t("after_collect_sec"))
        return fresh

    def _report(self, item: loot_mod.Loot, img: np.ndarray) -> loot_mod.Loot:
        """Passa o item pelo catálogo (nome/raridade certos), registra e avisa. Devolve o item corrigido."""
        snap = loot_mod.item_snapshot(img, item)
        first_in_catalog = False
        if self.catalog is not None:
            rec = self.catalog.record(item.name, item.rarity, snap)
            if rec.corrected:
                log.info("Nome corrigido pelo catálogo: %r -> %r", item.name, rec.name)
            if rec.first_time:
                first_in_catalog = True
                log.info("Item novo no catálogo: %s", rec.name)
            if rec.rarity != item.rarity:
                log.info("Raridade pelo catálogo: %s (cor lida: %s)", rec.rarity, item.rarity)
            item = replace(item, name=rec.name, rarity=rec.rarity)
        log.info("Pegou: %s x%d [%s]%s", item.name, item.quantity, item.rarity,
                 " NEW!" if item.is_new else "")
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
            image=snap if d.get("send_image", True) else None,
            is_new=item.is_new,
            first_in_catalog=first_in_catalog,
        ))
        return item

    # ---------- laço ----------
    # ---------- iscas ----------
    def _baits_on(self) -> bool:
        return self.baits is not None and bool(self.cfg["baits"].get("enabled", True))

    def _report_bait(self) -> None:
        if self._baits_on():
            self.cb.bait(self.baits.summary(self.cfg["baits"]["infinite"]), self.baits.warning)

    def _maybe_check_baits(self) -> None:
        if self._menu_stuck and not self._close_menu(bait_menu.BaitMenu(self)):
            raise Recoverable("o menu do jogo continua aberto", self._safe_shot())
        if not self._baits_on() or self.cycles < self._bait_retry_at:
            return
        c = self.cfg["baits"]
        if self.bait_check_requested or self.baits.needs_check(int(c["recheck_at"]), c["infinite"]):
            self.check_baits()

    def check_baits(self) -> None:
        """Abre o inventário, conta as iscas e troca se a equipada acabou."""
        c = self.cfg["baits"]
        order, infinite = list(c["order"]), list(c["infinite"])
        self.bait_check_requested = False
        menu = bait_menu.BaitMenu(self)
        self.cb.status("Conferindo as iscas no inventário...")
        try:
            menu.open()
            infos = {name: menu.inspect(name) for name in order}
            st = self.baits
            st.owned = [n for n, i in infos.items() if i.owned]
            st.counts = {n: (None if n in infinite else i.count) for n, i in infos.items() if i.owned}
            before = next((n for n, i in infos.items() if i.equipped), None)
            st.equipped = before
            log.info("Iscas no inventário: %s | equipada: %s",
                     {n: ("não tem" if not i.owned else i.count) for n, i in infos.items()}, before)
            self._switch_bait_if_needed(menu, order, infinite, before)
            st.mark_checked()
        except bait_menu.MenuError as exc:
            log.error("Conferência de iscas falhou: %s", exc)
            logbook.save_evidence(self._safe_shot(), "iscas " + str(exc))
            self._bait_retry_at = self.cycles + BAIT_RETRY_CYCLES
        finally:
            closed = self._close_menu(menu)
            if self.bait_path is not None:
                self.baits.save(self.bait_path)
            self._report_bait()
        if not closed:
            raise Recoverable("o menu do jogo não fechou", self._safe_shot())

    def _close_menu(self, menu) -> bool:
        """Fecha o menu. Enquanto ele estiver aberto a pesca não aperta nenhuma tecla."""
        try:
            menu.close()
        except bait_menu.MenuError as exc:
            log.error("Não consegui fechar o menu: %s", exc)
            self._menu_stuck = True
            return False
        self._menu_stuck = False
        return True

    def _switch_bait_if_needed(self, menu, order: list[str], infinite: list[str], current: str | None) -> None:
        st = self.baits
        best = st.choose(order, infinite)
        current_ok = current is not None and st.usable(current, infinite)
        better = (best is not None and current in order and order.index(best) < order.index(current))
        if best is None:
            if not self._no_bait_warned:
                self._no_bait_warned = True
                msg = "Acabaram as iscas: continuando a pescar sem isca. Compre mais quando voltar."
                log.warning(msg)
                self._notify("⚠️ " + msg)
            return
        if best == current or (current_ok and not better):
            return
        if not menu.equip(best):
            log.error("Não consegui equipar a isca %s", best)
            logbook.save_evidence(self._safe_shot(), "equipar isca")
            return
        st.equipped = best
        if current and not current_ok:
            msg = f"A isca {current} acabou: troquei para {best}. Compre mais quando voltar."
        else:
            msg = f"Isca trocada: {current or 'nenhuma'} → {best}."
        log.warning(msg)
        self._notify("🎣 " + msg)
        self.cb.status(msg)

    def one_cycle(self) -> None:
        self.cycles += 1
        log.debug("---- ciclo %d ----", self.cycles)
        cycle_start = time.perf_counter()
        self._maybe_check_baits()
        self.ensure_rod()
        self.check_camera()
        self.cast()
        if not self.minigame():
            self.failed_casts += 1
            limit = int(self.cfg["limits"]["max_failed_casts"])
            self.cb.status(f"Nenhum peixe mordeu ({self.failed_casts}/{limit}). Tentando de novo...")
            if self.failed_casts >= limit:
                self.failed_casts = 0
                _, img = self.frame()
                raise Recoverable(f"{limit} lançamentos seguidos sem minigame (caiu na água? vara presa?)", img)
            return
        self.failed_casts = 0
        self.recoveries = 0
        self.collect()
        if self._baits_on():
            # o jogo gasta 1 isca a cada mordida resolvida (pegando ou não)
            self.baits.consume(time.perf_counter() - cycle_start, self.cfg["baits"]["infinite"])
            if self.bait_path is not None:
                self.baits.save(self.bait_path)
            self._report_bait()
        if self.cycles % STATS_EVERY_CYCLES == 0:
            self._log_stats()

    def _log_stats(self) -> None:
        s = self.session
        log.info("Resumo: %s rodando, %d ciclos, %d itens, %d perdidos, %d recuperações seguidas",
                 s.elapsed_text(), self.cycles, s.catches, s.misses, self.recoveries)

    def _recover(self, msg: str, img: np.ndarray | None) -> None:
        """Registra o problema, avisa, espera e deixa o laço tentar de novo."""
        self.mouse.release()
        screen.release_key("t")
        self.recoveries += 1
        limit = int(self.cfg["limits"]["max_recoveries"])
        logbook.save_evidence(img, msg)
        if self.recoveries > limit:
            log.error("Desistindo depois de %d recuperações seguidas: %s", limit, msg)
            self._notify(f"🛑 Macro parou depois de {limit} tentativas de recuperação: {msg}")
            raise StopRun(f"Parei: {msg} ({limit} tentativas sem sucesso).")
        wait = self.t("recovery_wait_sec")
        log.error("Recuperação %d/%d: %s. Tentando de novo em %.0fs.", self.recoveries, limit, msg, wait)
        self._notify(f"⚠️ {msg}. Tentando de novo em {wait:.0f}s ({self.recoveries}/{limit}).",
                     ping=self.recoveries == 1)
        self.cb.status(f"Recuperando ({self.recoveries}/{limit}): {msg}. Nova tentativa em {wait:.0f}s.")
        self.sleep(wait)

    def _safe_shot(self) -> np.ndarray | None:
        try:
            return self.grabber.grab(window.client_rect(self.hwnd)) if self.hwnd else None
        except Exception:
            log.exception("Também não consegui tirar print")
            return None

    def run(self, stop: threading.Event) -> str:
        """Roda até parar. Devolve o motivo da parada."""
        self._stop = stop
        if not self.cfg.get("cast_point"):
            return "Marque o ponto de lançamento primeiro (F2)."
        self.hwnd = window.find_roblox()
        if self.hwnd is None:
            return "Roblox não encontrado. Abra o jogo."
        window.focus(self.hwnd)
        window.keep_awake(True)
        self.grabber = screen.Grabber()
        log.info("==== Início: janela %s, ponto %s, área %s, trava bússola=%s ====",
                 window.client_rect(self.hwnd), self.cfg["cast_point"], self.cfg["scan_area"],
                 bool(self.cfg.get("compass_lock")) and self.compass.ready)
        reason = "Parado."
        self._report_bait()
        try:
            while True:
                try:
                    self.one_cycle()
                except Recoverable as exc:
                    self._recover(str(exc), exc.img)
                except StopRun:
                    raise
                except Exception as exc:  # bug inesperado: registra tudo e segue pescando
                    log.exception("Erro inesperado no ciclo %d", self.cycles)
                    self._recover(f"erro inesperado ({type(exc).__name__}: {exc})", self._safe_shot())
        except StopRun as exc:
            reason = str(exc) or "Parado."
            return reason
        finally:
            window.keep_awake(False)
            log.info("==== Fim: %s ====", reason)
            self._log_stats()
            self.mouse.release()
            screen.release_key("t")
            self.grabber.close()
