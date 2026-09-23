"""Janela principal da macro de pesca do Slayers 2."""
from __future__ import annotations

import copy
import os
import queue
import threading
from typing import Callable

import customtkinter as ctk
import cv2
import keyboard
from PIL import Image

import config
import logbook
import screen
import window
from compass import CompassLock
from cycle import Callbacks, Fisher
from pickers import AreaPicker, PointPicker
from session import Session
from tabs import MUTED, RARITY_HEX, AdvancedTab, DiscordTab, SessionTab, SetupTab
from webhook import DiscordNotifier

COMPASS_FILE = config.CALIBRATION_DIR / "bussola.npz"
SAVE_DELAY_MS = 400
PUMP_MS = 30
TICK_MS = 1000
FOCUS_DELAY_MS = 350
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
        self.geometry("470x760")
        self.minsize(440, 640)

        self.cfg = config.load()
        self.session = Session(log_dir=config.LOG_DIR)
        self.compass = CompassLock()
        self.compass.load(COMPASS_FILE)
        self._posted: queue.SimpleQueue = queue.SimpleQueue()
        self.notifier = DiscordNotifier(on_error=lambda m: self.post(lambda: self.set_status(f"Discord: {m}")))
        self.apply_discord()

        self._save_job: str | None = None
        self._stop = threading.Event()
        self._running = False
        self._listening: str | None = None
        self._hotkey_handles: list = []
        self._picker_open = False
        self._snapshot = None  # mantém a imagem viva (senão o Tk apaga)

        self._build()
        self.apply_on_top()
        self.register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<KeyPress>", self._on_key)
        self.after(PUMP_MS, self._pump)
        self.after(TICK_MS, self._tick)

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

        self.tabs = ctk.CTkTabview(self, corner_radius=12)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=6)
        for name in ("Sessão", "Configurar", "Discord", "Avançado"):
            self.tabs.add(name)
        self.session_tab = SessionTab(self, self.tabs.tab("Sessão"))
        self.setup_tab = SetupTab(self, self.tabs.tab("Configurar"))
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
        self.after(TICK_MS, self._tick)

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
    def toggle_run(self) -> None:
        if self._listening or self._picker_open:
            return
        if self._running:
            self._stop.set()
            self.set_status("Parando...")
            return
        if not self.cfg.get("cast_point"):
            self.set_status("Marque o ponto de lançamento antes de começar.")
            return
        self._save_now()
        self._stop = threading.Event()
        self._running = True
        self.session.start()
        self._render_running()
        cb = Callbacks(status=lambda m: self.post(lambda: self.set_status(m)),
                       loot=lambda items, snap: self.post(lambda: self._on_loot(items, snap)))
        fisher = Fisher(copy.deepcopy(self.cfg), cb, self.session, self.notifier, self.compass)
        threading.Thread(target=self._run_worker, args=(fisher,), daemon=True).start()

    def _run_worker(self, fisher: Fisher) -> None:
        try:
            reason = fisher.run(self._stop)
        except Exception as exc:  # erro inesperado: mostra em vez de fechar em silêncio
            reason = f"Erro inesperado: {exc}"
        self.post(lambda: self._on_stopped(reason))

    def open_logs(self) -> None:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(config.LOG_DIR)

    def new_session(self) -> None:
        """Zera tempo e contagens (o CSV da sessão anterior continua salvo em logs/)."""
        if self._running:
            self.set_status("Pare a pesca antes de zerar a sessão.")
            return
        self.session = Session(log_dir=config.LOG_DIR)
        self.session_tab.reset()
        self._refresh_stats()
        self.set_status("Sessão zerada.")

    def _on_stopped(self, reason: str) -> None:
        self._running = False
        self.session.pause()
        self._render_running()
        self.set_status(reason)
        self._refresh_stats()

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
        self._snapshot = image
        self.session_tab.show_last(image, f"  {item.name}  x{item.quantity}")
        self.session_tab.last_img.configure(text_color=RARITY_HEX.get(item.rarity, "#ffffff"))

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

        def done(area) -> None:
            self._picker_open = False
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
        self._stop.set()
        keyboard.unhook_all_hotkeys()
        self._save_now()
        self.destroy()


def main() -> None:
    log = logbook.setup(config.LOG_DIR)
    log.info("Macro aberta.")
    window.ensure_dpi_awareness()
    App().mainloop()
    log.info("Macro fechada.")


if __name__ == "__main__":
    main()
