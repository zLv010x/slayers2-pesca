"""Janela principal da macro de pesca do Slayers 2."""
from __future__ import annotations

import copy
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk
import cv2
import keyboard
from PIL import Image

import capture_mode
import config
import logbook
import overlay
import screen
import shortcut
import window
from baits import BaitState
from catalog import Catalog
from compass import CompassLock
from cycle import Callbacks, Fisher
from pickers import AreaPicker, PointPicker
from restart_policy import RestartPolicy
from session import Session
from relog_tab import RelogTab
from tabs import MUTED, RARITY_HEX, AdvancedTab, DiscordTab, SessionTab, SetupTab
from webhook import DiscordNotifier

APP_ID = "zLv010x.Slayers2Pesca"
ICON_FILE = config.ROOT / "assets" / "icone.ico"
COMPASS_FILE = config.CALIBRATION_DIR / "bussola.npz"
BAIT_FILE = config.CALIBRATION_DIR / "iscas.json"
SESSION_FILE = config.LOG_DIR / "sessao-atual.json"
SAVE_DELAY_MS = 400
PUMP_MS = 30
TICK_MS = 1000
FOCUS_DELAY_MS = 350
MINIMIZE_DELAY_MS = 150
WARN_COVER_DELAY_MS = 1500  # depois de o Roblox vir para a frente
CLOSE_WAIT_SEC = 3.0
# Reinício automático na hora em que você marca ponto/atalho: tenta de novo depois disso.
RESTART_RETRY_MS = 30_000
SNAPSHOT_MAX_H = 60
GREEN, GREEN_HOVER = "#16a34a", "#15803d"
RED, RED_HOVER = "#dc2626", "#b91c1c"
AMBER = "#d97706"
IDLE = "#374151"
BAD_BORDER = "#ef4444"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Slayers 2 • Pesca")
        self._set_icon()
        self.geometry("470x760")
        self.minsize(440, 640)

        self.cfg = config.load()
        self.session = Session.load(config.LOG_DIR, SESSION_FILE)  # continua a de antes de fechar
        self.compass = CompassLock()
        self.compass.load(COMPASS_FILE)
        self.catalog = Catalog(config.CATALOG_DIR, config.CATALOG_LOCAL_DIR)
        self._tidy_catalog()
        self._prices = self.catalog.prices()  # valor dos peixes no overlay (fichas do catálogo)
        self.baits = BaitState.load(BAIT_FILE)
        self._fisher: Fisher | None = None
        self._bait_check_pending = False
        self._spawn_pending = False
        self._posted: queue.SimpleQueue = queue.SimpleQueue()
        self.notifier = DiscordNotifier(on_error=lambda m: self.post(lambda: self.set_status(f"Discord: {m}")))
        self.apply_discord()

        self._save_job: str | None = None
        self._stop = threading.Event()
        self._running = False
        self._listening: str | None = None
        self._hotkey_handles: list = []
        self._picker_open = False
        self._minimized_by_run = False
        self._worker: threading.Thread | None = None
        self._restart_policy = RestartPolicy()
        self._restart_job: str | None = None
        self._snapshot = None  # mantém a imagem viva (senão o Tk apaga)

        self._build()
        self._roblox_hwnd: int | None = None
        self._overlay_failed = False
        self.overlay = overlay.Overlay(self, self._overlay_rect, self._overlay_moved,
                                       config.PARTY_ZONE, self.cfg["ui"].get("overlay_pos"),
                                       capture_hidden=not self.cfg["ui"].get("show_in_capture", False))
        self.apply_on_top()
        self.register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<KeyPress>", self._on_key)
        self.after(PUMP_MS, self._pump)
        self.after(TICK_MS, self._tick)

    def _set_icon(self) -> None:
        try:
            self.iconbitmap(default=str(ICON_FILE))  # default: vale também para as outras janelas
        except tk.TclError as exc:
            logbook.get().warning("Ícone não carregado (%s): %s", ICON_FILE, exc)

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(head, text="Slayers 2  •  Pesca", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        self.pill = ctk.CTkLabel(head, text="Parado", corner_radius=12, fg_color=IDLE,
                                 height=26, width=110, font=ctk.CTkFont(size=12, weight="bold"))
        self.pill.pack(side="right")

        self.start_btn = ctk.CTkButton(self, height=52, corner_radius=12, font=ctk.CTkFont(size=18, weight="bold"),
                                       command=self.toggle_run)
        self.start_btn.pack(fill="x", padx=14, pady=6)

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.pack(fill="x", padx=10)
        self.stat_labels: dict[str, ctk.CTkLabel] = {}
        for key in ("Tempo", "Itens", "tracked", "Perdidos"):
            card = ctk.CTkFrame(stats, corner_radius=10)
            card.pack(side="left", expand=True, fill="x", padx=4)
            title = ctk.CTkLabel(card, text=key, text_color=MUTED, font=ctk.CTkFont(size=11))
            title.pack(pady=(6, 0))
            value = ctk.CTkLabel(card, text="-", font=ctk.CTkFont(size=16, weight="bold"))
            value.pack(pady=(0, 6))
            self.stat_labels[key] = value
            if key == "tracked":
                self._tracked_title = title

        self.bait_label = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont(size=12))
        self.bait_label.pack(fill="x", padx=18, pady=(4, 0))
        self._show_bait(self.baits.summary(self.cfg["baits"]["infinite"]), self.baits.warning)

        self.tabs = ctk.CTkTabview(self, corner_radius=12)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=6)
        for name in ("Sessão", "Configurar", "Relog", "Discord", "Avançado"):
            self.tabs.add(name)
        self.session_tab = SessionTab(self, self.tabs.tab("Sessão"))
        self.setup_tab = SetupTab(self, self.tabs.tab("Configurar"))
        self.relog_tab = RelogTab(self, self.tabs.tab("Relog"))
        self.discord_tab = DiscordTab(self, self.tabs.tab("Discord"))
        self._adv_parent = self.tabs.tab("Avançado")
        self.adv_tab = AdvancedTab(self, self._adv_parent, self.reset_advanced)

        self.status = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", wraplength=440, justify="left")
        self.status.pack(fill="x", padx=16, pady=(0, 10))
        self._render_running()
        self._refresh_stats()
        hk = self.cfg["hotkeys"]
        if not self.cfg.get("cast_point"):
            self.set_status(f"Primeiro passo: marque o ponto de lançamento ({hk['set_cast_point']}).")
        else:
            self.set_status(f"Pronto. {hk['start_stop']} começa a pescar.")

    def _render_running(self) -> None:
        key = self.cfg["hotkeys"]["start_stop"]
        if self._running:
            self.start_btn.configure(text=f"■  Parar   ({key})", fg_color=RED, hover_color=RED_HOVER)
            self.pill.configure(text="Pescando", fg_color=GREEN)
        else:
            self.start_btn.configure(text=f"▶  Iniciar   ({key})", fg_color=GREEN, hover_color=GREEN_HOVER)
            self.pill.configure(text="Parado", fg_color=IDLE)

    # ------------------------------------------------------------ helpers usados pelas abas
    def number_entry(self, parent, store: dict, key: str, width: int = 70, cast: Callable = float) -> ctk.CTkEntry:
        """Campo numérico que salva ao digitar e NUNCA apaga o que você está digitando."""
        entry = ctk.CTkEntry(parent, width=width, justify="center")
        entry.insert(0, str(store[key]))
        normal = entry.cget("border_color")

        def changed(_e=None) -> None:
            try:
                value = cast(entry.get().replace(",", ".").strip())
            except ValueError:
                entry.configure(border_color=BAD_BORDER)
                return
            if value < 0:
                entry.configure(border_color=BAD_BORDER)
                return
            entry.configure(border_color=normal)
            store[key] = value
            self.save_soon()

        entry.bind("<KeyRelease>", changed)
        return entry

    def save_soon(self) -> None:
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(SAVE_DELAY_MS, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        try:
            config.save(self.cfg)
        except OSError as exc:
            self.set_status(f"Não consegui salvar o config: {exc}")

    def _tidy_catalog(self) -> None:
        """Junta no item certo as leituras erradas que versões antigas gravaram como itens novos."""
        try:
            changes = self.catalog.tidy()
        except Exception:  # catálogo é conforto: nunca pode impedir a macro de abrir
            logbook.get().exception("Não consegui arrumar o catálogo local")
            return
        for old, new in changes:
            logbook.get().info("Catálogo arrumado: %r -> %s", old, repr(new) if new else "apagado (lixo do OCR)")

    def _minimize(self) -> None:
        try:
            self.iconify()
        except Exception:  # minimizar é conforto: nunca pode atrapalhar a pesca
            logbook.get().exception("Não consegui minimizar a janela")

    def _restore_window(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.apply_on_top()
        except Exception:
            logbook.get().exception("Não consegui restaurar a janela")

    def apply_on_top(self) -> None:
        self.attributes("-topmost", bool(self.cfg["ui"].get("always_on_top", True)))

    def apply_discord(self) -> None:
        d = self.cfg["discord"]
        self.notifier.url = d["webhook_url"]
        self.notifier.user_id = d["user_id"]
        self.notifier.ping_rarities = set(d["ping_rarities"])

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)
        if self._running:
            for prefix, label in (("Pausado", "Pausado"), ("Recuperando", "Recuperando")):
                if text.startswith(prefix):
                    self.pill.configure(text=label, fg_color=AMBER)
                    break
            else:
                self.pill.configure(text="Pescando", fg_color=GREEN)

    def post(self, fn: Callable[[], None]) -> None:
        """Agenda uma função para rodar na thread da interface."""
        self._posted.put(fn)

    def _pump(self) -> None:
        try:
            while True:
                fn = self._posted.get_nowait()
                try:
                    fn()
                except Exception:  # um erro na tela nunca pode derrubar a macro
                    logbook.get().exception("Erro ao atualizar a interface")
        except queue.Empty:
            pass
        self.after(PUMP_MS, self._pump)

    def _tick(self) -> None:
        self._refresh_stats()
        self._update_overlay()
        self.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ overlay
    def _overlay_rect(self) -> window.Rect | None:
        """Onde o jogo está, só lendo (sem trazer o Roblox para a frente). None = esconder:
        overlay desligado, jogo fechado, ou nem o Roblox nem a macro na frente."""
        if not self.cfg["ui"].get("overlay", True):
            return None
        if not self._roblox_hwnd or window.client_rect(self._roblox_hwnd) is None:
            self._roblox_hwnd = window.find_roblox()
        if self._roblox_hwnd is None:
            return None
        if not (window.is_foreground(self._roblox_hwnd) or window.is_foreground(window.root_hwnd(self))):
            return None
        return window.client_rect(self._roblox_hwnd)

    def _overlay_moved(self, pos: dict) -> None:
        self.cfg["ui"]["overlay_pos"] = pos
        self.save_soon()

    def _update_overlay(self) -> None:
        try:
            elapsed, counts, baits = self.session.overlay_snapshot()
            self.overlay.refresh(overlay.build_lines(elapsed, counts, baits, prices=self._prices))
            self.overlay.follow()
        except Exception:  # o overlay é só para ver: nunca pode atrapalhar a macro
            if not self._overlay_failed:
                self._overlay_failed = True
                logbook.get().exception("Erro no overlay")

    def apply_overlay(self) -> None:
        if not self.cfg["ui"].get("overlay", True):
            self.overlay.hide()
        self._update_overlay()

    def apply_capture_mode(self) -> None:
        """Normal: pescando, a janela e o overlay somem de qualquer print (a macro não se vê).
        Modo Parsec: aparecem, e a macro se apaga dos próprios prints (capture_mode)."""
        visible = bool(self.cfg["ui"].get("show_in_capture", False))
        if visible:  # já em camadas aqui, na thread do Tk (a da pesca só muda a opacidade)
            window.set_alpha(window.root_hwnd(self), window.OPAQUE)
        self.overlay.set_capture_hidden(not visible)
        if self._running and not window.set_capture_excluded(self, not visible) and not visible:
            logbook.get().warning("Não deu para esconder a janela da macro dos prints (Windows antigo?)")
        capture_mode.set_own_windows([window.root_hwnd(self), window.root_hwnd(self.overlay)] if visible else [])
        if visible and self._running:
            self.after(MINIMIZE_DELAY_MS + WARN_COVER_DELAY_MS, self._warn_covered_areas)

    def _warn_covered_areas(self) -> None:
        """Modo Parsec: a macro não enxerga o que a janela dela cobre. Avisa se for algo importante."""
        hwnd = window.find_roblox()
        game = window.client_rect(hwnd) if hwnd else None
        if game is None:
            return
        covered: set[str] = set()
        for widget in (self, self.overlay):
            win = window.visible_rect(window.root_hwnd(widget))
            if win is not None:
                covered.update(capture_mode.covered_areas(win, game, self.cfg))
        if covered:
            msg = ("Modo Parsec: a janela da macro ou o overlay está cobrindo " + ", ".join(sorted(covered))
                   + ". Arraste para o canto esquerdo, senão a macro não enxerga essa parte.")
            logbook.get().warning(msg)
            self.set_status(msg)

    def reset_overlay(self) -> None:
        self.cfg["ui"]["overlay_pos"] = None
        self.save_soon()
        self.overlay.reset_position()
        self.set_status("Overlay de volta para cima da party.")

    def _refresh_stats(self) -> None:
        s = self.session
        tracked = self.cfg["discord"].get("tracked_item", "").strip()
        self.stat_labels["Tempo"].configure(text=s.elapsed_text() if s.elapsed_seconds() >= 1 else "-")
        self.stat_labels["Itens"].configure(text=str(s.catches))
        self._tracked_title.configure(text=tracked or "Item")
        self.stat_labels["tracked"].configure(text=str(s.total_of(tracked)) if tracked else "-")
        self.stat_labels["Perdidos"].configure(text=str(s.misses))
        self.session_tab.refresh()

    # ------------------------------------------------------------ pesca
    def toggle_run(self, by_user: bool = True) -> None:
        if self._listening or self._picker_open:
            return
        if self._running:
            self._stop.set()
            self.set_status("Parando...")
            return
        self._cancel_auto_restart()
        if not self.cfg.get("cast_point"):
            self.set_status("Marque o ponto de lançamento antes de começar.")
            return
        self._save_now()
        self._stop = threading.Event()
        self._running = True
        self.session.start()
        self.apply_capture_mode()
        self._render_running()
        self.overlay.set_clickthrough(True)  # pescando: nenhum clique da macro pode parar no overlay
        cb = Callbacks(status=lambda m: self.post(lambda: self.set_status(m)),
                       loot=lambda items, snap: self.post(lambda: self._on_loot(items, snap)),
                       bait=lambda text, warn: self.post(lambda: self._show_bait(text, warn)),
                       spawn_set=lambda ok: self.post(lambda: self._on_spawn_set(ok)))
        fisher = Fisher(copy.deepcopy(self.cfg), cb, self.session, self.notifier, self.compass, self.catalog,
                        baits=self.baits, bait_path=BAIT_FILE)
        fisher.bait_check_requested = self._bait_check_pending
        self._bait_check_pending = False
        fisher.spawn_requested = self._spawn_pending
        fisher.spawn_auto_allowed = by_user  # reinício sozinho nunca seta o spawn
        self._spawn_pending = False
        self._fisher = fisher
        self._worker = threading.Thread(target=self._run_worker, args=(fisher,), daemon=True)
        self._worker.start()
        if self.cfg["ui"].get("minimize_on_start", True):
            self._minimized_by_run = True
            self.after(MINIMIZE_DELAY_MS, self._minimize)

    def _run_worker(self, fisher: Fisher) -> None:
        try:
            reason = fisher.run(self._stop)
        except Exception as exc:  # erro inesperado: mostra em vez de fechar em silêncio
            reason = f"Erro inesperado: {exc}"
        self.post(lambda: self._on_stopped(reason))

    def open_logs(self) -> None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(config.LOG_DIR)

    def _show_bait(self, text: str, warn: bool) -> None:
        if not self.cfg["baits"].get("enabled", True):
            self.bait_label.configure(text="")
            return
        self.bait_label.configure(text=("⚠️ " if warn else "🎣 ") + text,
                                  text_color=AMBER if warn else MUTED)

    def request_bait_check(self) -> None:
        if self._running and self._fisher is not None:
            self._fisher.bait_check_requested = True
            self.set_status("Vou conferir as iscas no começo do próximo ciclo.")
        else:
            self._bait_check_pending = True
            self.set_status("Vou conferir as iscas quando você iniciar a pesca.")

    def request_set_spawn(self) -> None:
        if self._running and self._fisher is not None:
            self._fisher.spawn_requested = True
            self.set_status("Vou setar o spawn no começo do próximo ciclo.")
        else:
            self._spawn_pending = True
            self.set_status("Vou setar o spawn quando você iniciar a pesca (fique no ponto de pesca).")

    def _on_spawn_set(self, ok: bool) -> None:
        if ok:
            self.cfg["relog"]["spawn_set"] = True
            self.save_soon()
        self.relog_tab.sync()
        self.set_status("Spawn setado no ponto de pesca." if ok else
                        "Não consegui setar o spawn: veja o log e sete na mão.")

    def new_session(self) -> None:
        """Resetar: apaga histórico, contagens e tempo guardados (o CSV continua em logs/)."""
        if self._running:
            self.set_status("Pare a pesca antes de resetar a sessão.")
            return
        if not messagebox.askyesno("Resetar sessão", "Apagar o histórico, as contagens e o tempo desta "
                                   "sessão?\n\n(O CSV com todos os itens continua em logs/.)", parent=self):
            return
        self.session.forget()
        self.session = Session(log_dir=config.LOG_DIR, state_path=SESSION_FILE)
        self.session_tab.reset()
        self._refresh_stats()
        self.set_status("Sessão resetada: histórico e contagens apagados.")

    def _on_stopped(self, reason: str) -> None:
        self._running = False
        if self._minimized_by_run:
            self._minimized_by_run = False
            self._restore_window()
        self.session.pause()
        window.set_capture_excluded(self, False)
        self.overlay.set_clickthrough(False)
        self._render_running()
        self.set_status(reason)
        self._refresh_stats()
        # F1/botão/fechar já marcam self._stop: só reinicia sozinho quando NÃO foi pedido.
        # No menu principal (servidor reiniciou) reiniciar não adianta: precisa alguém entrar no jogo.
        for_good = self._fisher is not None and self._fisher.stop_for_good
        if not self._stop.is_set() and not for_good:
            self._schedule_auto_restart(reason)

    def _cancel_auto_restart(self) -> None:
        if self._restart_job is not None:
            self.after_cancel(self._restart_job)
            self._restart_job = None

    def _notify_problem(self, text: str) -> None:
        if self.cfg["discord"].get("notify_problems", True):
            self.notifier.send_text(text, ping=True)

    def _schedule_auto_restart(self, reason: str) -> None:
        """A pesca parou sozinha (sem ninguém olhando): avisa e tenta de novo mais tarde."""
        wait_min = float(self.cfg["limits"].get("auto_restart_wait_min", 0))
        if wait_min <= 0:
            return
        limit = int(self.cfg["limits"].get("max_restarts_per_hour", 3))
        if not self._restart_policy.allowed(limit):
            self._notify_problem(
                f"🛑 Pesca parou ({reason}) e já tentou reiniciar sozinha {limit}x na última hora: "
                "vou esperar você dar uma olhada.")
            return
        self._notify_problem(f"⏸️ Pesca parou sozinha: {reason} Vou tentar de novo em {wait_min:.0f} min.")
        self.set_status(f"{reason} Reiniciando sozinho em {wait_min:.0f} min...")
        self._restart_job = self.after(int(wait_min * 60 * 1000), self._auto_restart)

    def _auto_restart(self) -> None:
        self._restart_job = None
        if self._running:
            return
        if self._listening or self._picker_open:
            # marcando ponto/atalho agora: tenta daqui a pouco, sem gastar a vez
            self._restart_job = self.after(RESTART_RETRY_MS, self._auto_restart)
            return
        self.toggle_run(by_user=False)
        if not self._running:
            self._notify_problem(f"⚠️ Não consegui reiniciar a pesca sozinha: {self.status.cget('text')}")
            return
        self._restart_policy.record_restart()
        self._notify_problem("🎣 Reiniciando a pesca sozinha.")

    def _on_loot(self, items: list, snapshot) -> None:
        self._refresh_stats()
        if not items:
            return
        item = items[-1]
        image = None
        if snapshot is not None:
            rgb = cv2.cvtColor(snapshot, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            scale = min(1.0, SNAPSHOT_MAX_H / max(h, 1))
            image = ctk.CTkImage(Image.fromarray(rgb), size=(max(1, int(w * scale)), max(1, int(h * scale))))
        # Troca primeiro a imagem na tela e só depois solta a antiga: soltar antes apaga a
        # imagem que o rótulo ainda usa ("image pyimage.. doesn't exist").
        self.session_tab.show_last(image, f"  {item.name}  x{item.quantity}")
        self.session_tab.last_img.configure(text_color=RARITY_HEX.get(item.rarity, "#ffffff"))
        self._snapshot = image

    # ------------------------------------------------------------ calibração
    def _game_rect(self) -> window.Rect | None:
        hwnd = window.find_roblox()
        if hwnd is None:
            self.set_status("Roblox não encontrado. Abra o jogo primeiro.")
            return None
        window.focus(hwnd)
        return window.client_rect(hwnd)

    def pick_cast_point(self) -> None:
        if self._running or self._picker_open:
            self.set_status("Pare a pesca antes de marcar o ponto.")
            return
        rect = self._game_rect()
        if rect is None:
            return
        self._picker_open = True
        self._minimize()
        # Espera o Roblox vir para frente e guarda a bússola antes de cobrir a tela.
        self.after(FOCUS_DELAY_MS, lambda: self._open_point_picker(rect))

    def _open_point_picker(self, rect: window.Rect) -> None:
        grabber = screen.Grabber()
        try:
            frame = grabber.grab(rect)
        finally:
            grabber.close()

        def done(point) -> None:
            self._picker_open = False
            self._restore_window()
            if point is None:
                self.set_status("Marcação cancelada.")
                return
            x, y = point
            if config.in_party_zone(x, y):
                self.set_status("Esse ponto fica em cima da lista da party. Escolha outro lugar na água.")
                return
            self.cfg["cast_point"] = {"x": x, "y": y}
            self.compass.capture(frame)
            config.CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
            self.compass.save(COMPASS_FILE)
            self.save_soon()
            self.setup_tab.refresh()
            self.set_status("Ponto de lançamento e câmera salvos ✓")

        PointPicker(self, rect, "Clique onde a vara deve lançar", done)

    def pick_scan_area(self) -> None:
        if self._running or self._picker_open:
            self.set_status("Pare a pesca antes de ajustar a área.")
            return
        rect = self._game_rect()
        if rect is None:
            return
        self._picker_open = True
        self._minimize()

        def done(area) -> None:
            self._picker_open = False
            self._restore_window()
            if area is None:
                self.set_status("Ajuste cancelado.")
                return
            self.cfg["scan_area"] = area
            self.save_soon()
            self.set_status("Área da barra salva ✓")

        self.after(FOCUS_DELAY_MS, lambda: AreaPicker(self, rect, self.cfg["scan_area"], done))

    def reset_advanced(self) -> None:
        for group in ("timings", "limits", "tracking"):
            self.cfg[group] = copy.deepcopy(config.DEFAULTS[group])
        self.save_soon()
        for child in self._adv_parent.winfo_children():
            child.destroy()
        self.adv_tab = AdvancedTab(self, self._adv_parent, self.reset_advanced)
        self.set_status("Ajustes avançados voltaram ao padrão.")

    def test_discord(self) -> None:
        if not self.notifier.enabled:
            self.set_status("Cole um link de webhook válido primeiro.")
            return
        self.notifier.send_text("✅ Teste da macro de pesca: webhook funcionando!", ping=True)
        self.set_status("Mensagem de teste enviada — confira o canal.")

    # ------------------------------------------------------------ atalhos (configuráveis)
    def register_hotkeys(self) -> None:
        for handle in self._hotkey_handles:
            keyboard.remove_hotkey(handle)
        self._hotkey_handles = []
        actions = {"start_stop": self.toggle_run, "set_cast_point": self.pick_cast_point, "exit": self.close}
        for key, action in actions.items():
            name = self.cfg["hotkeys"][key].lower()
            try:
                self._hotkey_handles.append(keyboard.add_hotkey(name, lambda a=action: self.post(a)))
            except ValueError:
                self.set_status(f"Atalho inválido: {name}")

    def listen_hotkey(self, key: str) -> None:
        self._listening = key
        self.set_status("Aperte a nova tecla (Esc cancela)...")
        self.focus_force()

    def _on_key(self, event) -> None:
        if self._listening is None:
            return
        key, self._listening = self._listening, None
        name = event.keysym
        if name == "Escape":
            self.set_status("Troca de atalho cancelada.")
            return
        is_fkey = name[:1] == "F" and name[1:].isdigit()
        name = name.upper() if (len(name) == 1 or is_fkey) else name.lower()
        if name.lower() in {v.lower() for k, v in self.cfg["hotkeys"].items() if k != key}:
            self.set_status(f"{name} já está em uso por outro atalho.")
            return
        if name.lower() in {"t", str(self.cfg["rod_key"]).lower()}:
            self.set_status(f"{name} é usada pelo jogo (T / vara). Escolha outra.")
            return
        self.cfg["hotkeys"][key] = name
        self.register_hotkeys()
        self.setup_tab.refresh()
        self._render_running()
        self.save_soon()
        self.set_status(f"Atalho salvo: {name}")

    def close(self) -> None:
        self._cancel_auto_restart()
        self._stop.set()
        # espera a pesca soltar T/mouse (o finally dela) antes de fechar o programa
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=CLOSE_WAIT_SEC)
            if self._worker.is_alive():
                # não parou a tempo: a thread morre junto com o programa sem soltar nada
                logbook.get().warning("A pesca não parou em %.0fs: soltando T e mouse antes de fechar.",
                                      CLOSE_WAIT_SEC)
                screen.release_key("t")
                screen.MouseButton().release()
        keyboard.unhook_all_hotkeys()
        self._save_now()
        self.destroy()


def main() -> None:
    log = logbook.setup(config.LOG_DIR)
    log.info("Macro aberta.")
    window.ensure_dpi_awareness()
    window.set_app_id(APP_ID)
    threading.Thread(target=shortcut.ensure, args=(config.ROOT,), daemon=True).start()
    App().mainloop()
    log.info("Macro fechada.")


if __name__ == "__main__":
    main()
