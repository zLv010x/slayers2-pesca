"""Abas da interface: Sessão, Configurar, Discord e Avançado."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

import webhook

if TYPE_CHECKING:
    from app import App

RARITY_ORDER = ("mythic", "legendary", "epic", "rare", "common")
RARITY_HEX = {
    "mythic": "#e11d48",
    "legendary": "#f5b400",
    "epic": "#a855f7",
    "rare": "#3b82f6",
    "common": "#9aa0a6",
}
MUTED = ("#6b7280", "#9ca3af")
CARD = ("#eef2f7", "#1f2937")
OK = "#22c55e"
BAD = "#ef4444"

ADVANCED_FIELDS = {
    "timings": [
        ("after_cast_sec", "Espera após lançar (s)", "Pausa entre o clique e começar a procurar o minigame."),
        ("minigame_start_timeout_sec", "Tempo máx. sem morder (s)", "Sem minigame nesse tempo = lança de novo."),
        ("minigame_max_sec", "Duração máx. do minigame (s)", "Segurança: depois disso vai coletar."),
        ("ball_lost_sec", "Minigame acabou após (s)", "Quadrado branco sumido por esse tempo = acabou."),
        ("after_minigame_sec", "Espera antes do T (s)", "Pausa entre o fim do minigame e segurar T."),
        ("collect_hold_sec", "Segurar T por (s)", "Quanto tempo segura T para pegar o item."),
        ("popup_wait_sec", "Esperar aviso do item (s)", "Tempo extra procurando o nome do item."),
        ("after_collect_sec", "Espera após coletar (s)", "Pausa antes do próximo lançamento."),
        ("rod_equip_wait_sec", "Espera ao equipar vara (s)", "Depois de apertar a tecla da vara."),
        ("recovery_wait_sec", "Espera ao recuperar (s)", "Depois de um problema, espera isso e tenta de novo."),
        ("refocus_after_sec", "Trazer Roblox de volta após (s)",
         "Se outra janela ficar na frente, traz o jogo de volta depois disso. 0 = nunca."),
    ],
    "limits": [
        ("rod_retries", "Tentativas de equipar vara", "Se não equipar depois disso, para e avisa."),
        ("max_failed_casts", "Lançamentos sem peixe seguidos", "Passou disso, conta como problema (caiu na água?)."),
        ("max_recoveries", "Problemas seguidos até desistir", "Recuperações seguidas sem pegar peixe antes de parar."),
    ],
    "tracking": [
        ("task_fps", "FPS do minigame", "Prints por segundo no minigame. Baixe se o PC travar."),
        ("latency_s", "Latência (s)", "Quanto prevê à frente. Aumente se passar da zona verde."),
        ("hysteresis_px", "Zona morta (px)", "Maior = segura/solta com menos frequência."),
        ("aim_offset", "Mira (alturas do quadrado)", "Negativo mira acima do centro da zona."),
        ("accel_hold", "Aceleração segurando", "Quanto o quadrado sobe segurando."),
        ("accel_release", "Aceleração soltando", "Quanto o quadrado desce soltando."),
    ],
}


def section(parent, title: str) -> ctk.CTkFrame:
    ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(
        fill="x", padx=4, pady=(10, 2))
    box = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
    box.pack(fill="x", padx=2, pady=(0, 4))
    return box


def hint(parent, text: str) -> ctk.CTkLabel:
    lbl = ctk.CTkLabel(parent, text=text, text_color=MUTED, font=ctk.CTkFont(size=11),
                       justify="left", anchor="w", wraplength=340)
    lbl.pack(fill="x", padx=10, pady=(0, 6))
    return lbl


def row(parent) -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, fg_color="transparent")
    f.pack(fill="x", padx=10, pady=4)
    return f


# ---------------------------------------------------------------- Sessão
class SessionTab:
    def __init__(self, app: "App", parent) -> None:
        self.app = app
        chips = ctk.CTkFrame(parent, fg_color="transparent")
        chips.pack(fill="x", pady=(6, 4))
        self.chips: dict[str, ctk.CTkLabel] = {}
        for rarity in RARITY_ORDER:
            chip = ctk.CTkLabel(chips, text="0", height=26, corner_radius=13,
                                fg_color=RARITY_HEX[rarity], text_color="white",
                                font=ctk.CTkFont(size=11, weight="bold"))
            chip.pack(side="left", expand=True, fill="x", padx=2)
            self.chips[rarity] = chip

        last = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        last.pack(fill="x", pady=4)
        ctk.CTkLabel(last, text="Último item", text_color=MUTED, anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        self.last_img = ctk.CTkLabel(last, text="Nada ainda — boa pescaria!", height=70)
        self.last_img.pack(fill="x", padx=10, pady=(0, 8))

        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="Histórico", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=4)
        self.show_recent = ctk.CTkSwitch(head, text="mostrar", command=self._toggle_recent)
        self.show_recent.pack(side="right")
        ctk.CTkButton(head, text="Abrir logs", width=90, height=24, fg_color="#374151",
                      command=app.open_logs).pack(side="right", padx=8)
        ctk.CTkButton(head, text="Zerar", width=60, height=24, fg_color="#374151",
                      command=app.new_session).pack(side="right")
        if app.cfg["ui"].get("show_recent", True):
            self.show_recent.select()
        self.recent = ctk.CTkScrollableFrame(parent, fg_color=CARD, corner_radius=10, height=170)
        self._rows: list[ctk.CTkFrame] = []
        self._shown = 0
        self._toggle_recent(save=False)
        self.refresh()

    def _toggle_recent(self, save: bool = True) -> None:
        on = bool(self.show_recent.get())
        if on:
            self.recent.pack(fill="both", expand=True, pady=4)
        else:
            self.recent.pack_forget()
        if save:
            self.app.cfg["ui"]["show_recent"] = on
            self.app.save_soon()

    def refresh(self) -> None:
        s = self.app.session
        for rarity, chip in self.chips.items():
            chip.configure(text=f"{webhook.RARITY_LABELS[rarity]} {s.rarities.get(rarity, 0)}")
        if self._shown == s.catches:
            return
        self._shown = s.catches
        for r in self._rows:
            r.destroy()
        self._rows = []
        for hora, name, qty, rarity in s.last[:30]:
            line = ctk.CTkFrame(self.recent, fg_color="transparent")
            line.pack(fill="x", pady=1)
            ctk.CTkLabel(line, text="●", text_color=RARITY_HEX.get(rarity, "#9aa0a6"), width=14).pack(side="left")
            ctk.CTkLabel(line, text=f"{name}  x{qty}", anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(line, text=hora, text_color=MUTED).pack(side="right", padx=4)
            self._rows.append(line)

    def reset(self) -> None:
        self._shown = -1
        self.last_img.configure(image=None, text="Nada ainda — boa pescaria!", text_color=("gray10", "gray90"))
        self.refresh()

    def show_last(self, image, text: str) -> None:
        self.last_img.configure(image=image, text=text, compound="left")


# ---------------------------------------------------------------- Configurar
class SetupTab:
    def __init__(self, app: "App", parent) -> None:
        self.app = app
        cfg = app.cfg
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        box = section(scroll, "Ponto de lançamento")
        r = row(box)
        ctk.CTkButton(r, text="Marcar ponto", width=130, command=app.pick_cast_point).pack(side="left")
        self.cast_lbl = ctk.CTkLabel(r, text="", anchor="w")
        self.cast_lbl.pack(side="left", padx=10)
        hint(box, "Deixe a vara na mão e a câmera do jeito que quer pescar, depois marque. "
                  "A macro guarda a bússola e pausa se a câmera girar.")
        r = row(box)
        self.lock = ctk.CTkSwitch(r, text="Travar câmera pela bússola", command=self._save_lock)
        self.lock.pack(side="left")
        if cfg.get("compass_lock", True):
            self.lock.select()
        app.number_entry(r, cfg, "compass_tolerance_px", width=50, cast=int).pack(side="right")
        ctk.CTkLabel(r, text="tolerância px", text_color=MUTED).pack(side="right", padx=6)

        box = section(scroll, "Barra do minigame")
        r = row(box)
        ctk.CTkButton(r, text="Ajustar área", width=130, command=app.pick_scan_area).pack(side="left")
        ctk.CTkLabel(r, text="onde aparece a barra vertical", text_color=MUTED).pack(side="left", padx=10)

        box = section(scroll, "Vara")
        r = row(box)
        ctk.CTkLabel(r, text="Tecla da vara").pack(side="left")
        self.rod = ctk.CTkEntry(r, width=50, justify="center")
        self.rod.insert(0, cfg["rod_key"])
        self.rod.pack(side="left", padx=8)
        self.rod.bind("<KeyRelease>", lambda _e: self._save_rod())
        hint(box, "A macro confere a hotbar antes de lançar e só aperta a tecla se a vara não estiver na mão.")

        box = section(scroll, "Atalhos")
        labels = {"start_stop": "Iniciar / parar", "set_cast_point": "Marcar ponto", "exit": "Fechar macro"}
        self.hotkey_btns: dict[str, ctk.CTkButton] = {}
        for key, label in labels.items():
            r = row(box)
            ctk.CTkLabel(r, text=label).pack(side="left")
            btn = ctk.CTkButton(r, text=cfg["hotkeys"][key], width=80, fg_color="#374151",
                                command=lambda k=key: app.listen_hotkey(k))
            btn.pack(side="right")
            self.hotkey_btns[key] = btn

        box = section(scroll, "Janela")
        r = row(box)
        self.on_top = ctk.CTkSwitch(r, text="Sempre no topo", command=self._save_on_top)
        self.on_top.pack(side="left")
        if cfg["ui"].get("always_on_top", True):
            self.on_top.select()
        hint(box, "No Roblox: desligue Screen Shake e Shift Lock, senão a câmera mexe durante a pesca.")
        self.refresh()

    def refresh(self) -> None:
        pt = self.app.cfg.get("cast_point")
        lock = "  •  bússola ✓" if self.app.compass.ready else "  •  bússola ✗"
        self.cast_lbl.configure(
            text=(f"x {pt['x']:.3f}  y {pt['y']:.3f}{lock}" if pt else "não marcado"),
            text_color=(OK if pt else BAD))
        for key, btn in self.hotkey_btns.items():
            btn.configure(text=self.app.cfg["hotkeys"][key])

    def _save_lock(self) -> None:
        self.app.cfg["compass_lock"] = bool(self.lock.get())
        self.app.save_soon()

    def _save_rod(self) -> None:
        self.app.cfg["rod_key"] = self.rod.get().strip()[:10]
        self.app.save_soon()

    def _save_on_top(self) -> None:
        self.app.cfg["ui"]["always_on_top"] = bool(self.on_top.get())
        self.app.apply_on_top()
        self.app.save_soon()


# ---------------------------------------------------------------- Discord
class DiscordTab:
    def __init__(self, app: "App", parent) -> None:
        self.app = app
        d = app.cfg["discord"]
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        box = section(scroll, "Webhook do canal")
        r = row(box)
        self.url = ctk.CTkEntry(r, show="•", placeholder_text="https://discord.com/api/webhooks/...")
        if d["webhook_url"]:
            self.url.insert(0, d["webhook_url"])
        self.url.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text="ver", width=40, fg_color="#374151", command=self._toggle_eye).pack(side="left", padx=(6, 0))
        self.url_ok = hint(box, "")
        hint(box, "Canal → Editar → Integrações → Webhooks → Novo → Copiar URL. "
                  "O link funciona como senha: não compartilhe.")
        self.url.bind("<KeyRelease>", lambda _e: self._save())

        box = section(scroll, "Marcar você")
        r = row(box)
        ctk.CTkLabel(r, text="Seu ID do Discord").pack(side="left")
        self.uid = ctk.CTkEntry(r, placeholder_text="ex.: 123456789012345678")
        if d["user_id"]:
            self.uid.insert(0, d["user_id"])
        self.uid.pack(side="left", fill="x", expand=True, padx=8)
        self.uid.bind("<KeyRelease>", lambda _e: self._save())
        self.uid_ok = hint(box, "")
        r = row(box)
        ctk.CTkLabel(r, text="Marcar em:").pack(side="left")
        self.ping: dict[str, ctk.CTkCheckBox] = {}
        for rarity in ("mythic", "legendary", "epic"):
            cb = ctk.CTkCheckBox(r, text=webhook.RARITY_LABELS[rarity], width=20, command=self._save,
                                 fg_color=RARITY_HEX[rarity], hover_color=RARITY_HEX[rarity])
            cb.pack(side="left", padx=6)
            if rarity in d["ping_rarities"]:
                cb.select()
            self.ping[rarity] = cb

        box = section(scroll, "Mensagens")
        r = row(box)
        ctk.CTkLabel(r, text="Item com total em toda mensagem").pack(side="left")
        self.tracked = ctk.CTkEntry(r, width=110)
        self.tracked.insert(0, d["tracked_item"])
        self.tracked.pack(side="right")
        self.tracked.bind("<KeyRelease>", lambda _e: self._save())
        r = row(box)
        self.send_img = ctk.CTkSwitch(r, text="Mandar print do item", command=self._save)
        self.send_img.pack(side="left")
        if d["send_image"]:
            self.send_img.select()
        r = row(box)
        self.problems = ctk.CTkSwitch(r, text="Avisar quando a macro parar sozinha", command=self._save)
        self.problems.pack(side="left")
        if d["notify_problems"]:
            self.problems.select()
        r = row(box)
        ctk.CTkButton(r, text="Testar envio", command=app.test_discord).pack(side="left")
        self._validate()

    def _toggle_eye(self) -> None:
        self.url.configure(show="" if self.url.cget("show") else "•")

    def _validate(self) -> None:
        url, uid = self.url.get().strip(), self.uid.get().strip()
        if not url:
            self.url_ok.configure(text="Sem webhook: nada será enviado.", text_color=MUTED)
        elif webhook.valid_webhook(url):
            self.url_ok.configure(text="Link válido ✓", text_color=OK)
        else:
            self.url_ok.configure(text="Esse link não parece um webhook do Discord.", text_color=BAD)
        if not uid:
            self.uid_ok.configure(text="Sem ID: ninguém é marcado.", text_color=MUTED)
        elif webhook.valid_user_id(uid):
            self.uid_ok.configure(text="ID válido ✓", text_color=OK)
        else:
            self.uid_ok.configure(text="O ID tem só números (Modo desenvolvedor → Copiar ID).", text_color=BAD)

    def _save(self) -> None:
        d = self.app.cfg["discord"]
        d["webhook_url"] = self.url.get().strip()
        d["user_id"] = self.uid.get().strip()
        d["ping_rarities"] = [r for r, cb in self.ping.items() if cb.get()]
        d["tracked_item"] = self.tracked.get().strip()
        d["send_image"] = bool(self.send_img.get())
        d["notify_problems"] = bool(self.problems.get())
        self._validate()
        self.app.apply_discord()
        self.app.save_soon()


# ---------------------------------------------------------------- Avançado
class AdvancedTab:
    def __init__(self, app: "App", parent, on_reset: Callable[[], None]) -> None:
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        titles = {"timings": "Tempos", "limits": "Limites de segurança", "tracking": "Minigame"}
        for group, fields in ADVANCED_FIELDS.items():
            box = section(scroll, titles[group])
            for key, label, tip in fields:
                r = row(box)
                ctk.CTkLabel(r, text=label).pack(side="left")
                cast = int if group == "limits" else float
                app.number_entry(r, app.cfg[group], key, width=70, cast=cast).pack(side="right")
                hint(box, tip)
        ctk.CTkButton(scroll, text="Restaurar padrões", fg_color="#374151", command=on_reset).pack(pady=10)
