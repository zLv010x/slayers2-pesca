"""Abas da interface: Sessão, Configurar, Discord e Avançado (a aba Relog fica em relog_tab.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

import logbook
import webhook
from i18n import _

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
AMBER = "#d97706"
CHIP_OFF = ("#d1d5db", "#2b3340")   # etiqueta fora do filtro: apagada
RECENT_ROWS = 50

ADVANCED_FIELDS = {
    "timings": [
        ("after_cast_sec", "Espera após lançar (s)", "Pausa entre o clique e começar a procurar o minigame."),
        ("minigame_start_timeout_sec", "Tempo máx. sem morder (s)", "Sem minigame nesse tempo = lança de novo."),
        ("minigame_max_sec", "Duração máx. do minigame (s)", "Segurança: depois disso vai coletar."),
        ("ball_lost_sec", "Minigame acabou após (s)", "Quadrado branco sumido por esse tempo = acabou."),
        ("after_minigame_sec", "Espera antes do T (s)", "Pausa entre o fim do minigame e segurar T."),
        ("collect_hold_sec", "Segurar T por (s)", "Quanto tempo o jogo pede para segurar T."),
        ("collect_timeout_sec", "Tentar pegar da vara por (s)",
         "Se o item balança e o T recomeça, continua tentando até esse tempo."),
        ("ground_pickup_sec", "Tentar pegar do chão por (s)", "Depois de guardar a vara, tenta pegar do chão."),
        ("popup_wait_sec", "Esperar aviso do item (s)", "Tempo extra procurando o nome do item."),
        ("after_collect_sec", "Espera após coletar (s)", "Pausa antes do próximo lançamento."),
        ("rod_equip_wait_sec", "Espera ao equipar vara (s)", "Depois de apertar a tecla da vara."),
        ("recovery_wait_sec", "Espera ao recuperar (s)", "Depois de um problema, espera isso e tenta de novo."),
        ("refocus_after_sec", "Trazer Roblox de volta após (s)",
         "Se outra janela ficar na frente, traz o jogo de volta depois disso. 0 = nunca."),
        ("anti_idle_sec", "Anti-inatividade a cada (s)",
         "Numa pausa longa, mexe o mouse 1px para o jogo não desconectar por ficar parado. 0 desliga."),
    ],
    "limits": [
        ("rod_retries", "Tentativas de equipar vara", "Se não equipar depois disso, para e avisa."),
        ("max_failed_casts", "Lançamentos sem peixe seguidos", "Passou disso, conta como problema (caiu na água?)."),
        ("max_recoveries", "Problemas seguidos até desistir", "Recuperações seguidas sem pegar peixe antes de parar."),
        ("auto_restart_wait_min", "Reiniciar sozinho após (min)",
         "Se a pesca parar sozinha (não foi F1/botão/fechar), tenta de novo depois desse tempo. 0 desliga."),
        ("after_relog_failed_casts", "Lançamentos vazios após relog",
         "Depois de reconectar, tantos lançamentos sem peixe = nasceu longe da água: para e avisa."),
        ("max_restarts_per_hour", "Reinícios por hora (máx.)",
         "Depois de tentar reiniciar sozinha esse tanto de vezes numa hora, só avisa e espera você."),
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
        # Etiquetas de raridade = filtro do histórico: clicar liga/desliga. Só esconde da
        # lista; os drops continuam guardados e voltam quando a raridade é ligada de novo.
        self.hidden: set[str] = set()
        self.chips: dict[str, ctk.CTkButton] = {}
        for rarity in RARITY_ORDER:
            chip = ctk.CTkButton(chips, text="0", height=26, width=40, corner_radius=13,
                                 fg_color=RARITY_HEX[rarity], hover_color=RARITY_HEX[rarity],
                                 text_color="white", font=ctk.CTkFont(size=10, weight="bold"),
                                 command=lambda r=rarity: self.toggle_filter(r))
            chip.pack(side="left", expand=True, fill="x", padx=2)
            self.chips[rarity] = chip

        last = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        last.pack(fill="x", pady=4)
        ctk.CTkLabel(last, text=_("Último item"), text_color=MUTED, anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        self.last_img = ctk.CTkLabel(last, text=_("Nada ainda — boa pescaria!"), height=70)
        self.last_img.pack(fill="x", padx=10, pady=(0, 8))

        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=_("Histórico"), font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=4)
        self.show_recent = ctk.CTkSwitch(head, text=_("mostrar"), command=self._toggle_recent)
        self.show_recent.pack(side="right")
        ctk.CTkButton(head, text=_("Abrir logs"), width=90, height=24, fg_color="#374151",
                      command=app.open_logs).pack(side="right", padx=8)
        ctk.CTkButton(head, text=_("Resetar"), width=70, height=24, fg_color="#374151",
                      command=app.new_session).pack(side="right")
        if app.cfg["ui"].get("show_recent", True):
            self.show_recent.select()
        # Uma caixa de texto só (recriar 50 linhas de widgets travava a janela ~2,4 s por item)
        self.recent = ctk.CTkTextbox(parent, fg_color=CARD, corner_radius=10, height=170, wrap="none",
                                     font=ctk.CTkFont(size=12))
        for rarity, color in RARITY_HEX.items():
            self.recent.tag_config(rarity, foreground=color)
        self.recent.tag_config("muted", foreground=MUTED[1])
        self.recent.configure(state="disabled")
        self._chip_state: tuple | None = None
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

    def _empty_text(self, visible: set[str]) -> str:
        if not visible:
            return _("Todas as raridades desligadas: clique numa etiqueta para mostrar.")
        if self.hidden:
            chosen = ", ".join(webhook.RARITY_LABELS[r] for r in RARITY_ORDER if r in visible)
            return _("Nenhum item {chosen} nesta sessão.", chosen=chosen)
        return _("Nada ainda.")

    def toggle_filter(self, rarity: str) -> None:
        self.hidden ^= {rarity}
        self._shown = -1  # força redesenhar a lista
        self.refresh()

    def _paint_chips(self) -> None:
        s = self.app.session
        state = tuple((r, s.rarities.get(r, 0), r in self.hidden) for r in RARITY_ORDER)
        if state == self._chip_state:
            return  # nada mudou: redesenhar à toa pesa (roda a cada segundo)
        self._chip_state = state
        for rarity, chip in self.chips.items():
            on = rarity not in self.hidden
            color = RARITY_HEX[rarity]
            chip.configure(text=f"{webhook.RARITY_LABELS[rarity]} {s.rarities.get(rarity, 0)}",
                           fg_color=color if on else CHIP_OFF, hover_color=color,
                           text_color="white" if on else color)

    def refresh(self) -> None:
        s = self.app.session
        self._paint_chips()
        if self._shown == s.catches:
            return
        self._shown = s.catches
        self._chip_state = None  # etiqueta clicada: repinta
        visible = {r for r in RARITY_ORDER if r not in self.hidden}
        rows = s.recent(visible if self.hidden else None, RECENT_ROWS)
        box = self.recent
        box.configure(state="normal")
        box.delete("1.0", "end")
        if not rows:
            box.insert("end", self._empty_text(visible), "muted")
        for hora, name, qty, rarity in rows:
            box.insert("end", f"{hora}   ", "muted")
            box.insert("end", "● ", rarity if rarity in RARITY_HEX else "common")
            box.insert("end", f"{name}  x{qty}\n")
        box.configure(state="disabled")

    def reset(self) -> None:
        self._shown = -1
        self.last_img.configure(image=None, text=_("Nada ainda — boa pescaria!"), text_color=("gray10", "gray90"))
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

        box = section(scroll, _("Ponto de lançamento"))
        r = row(box)
        ctk.CTkButton(r, text=_("Marcar ponto"), width=130, command=app.pick_cast_point).pack(side="left")
        self.cast_lbl = ctk.CTkLabel(r, text="", anchor="w")
        self.cast_lbl.pack(side="left", padx=10)
        hint(box, _("Deixe a vara na mão e a câmera do jeito que quer pescar, depois marque. "
                  "A macro guarda a bússola e pausa se a câmera girar."))
        r = row(box)
        self.lock = ctk.CTkSwitch(r, text=_("Travar câmera pela bússola"), command=self._save_lock)
        self.lock.pack(side="left")
        if cfg.get("compass_lock", True):
            self.lock.select()
        app.number_entry(r, cfg, "compass_tolerance_px", width=50, cast=int).pack(side="right")
        ctk.CTkLabel(r, text=_("tolerância px"), text_color=MUTED).pack(side="right", padx=6)
        r = row(box)
        self.auto_camera = ctk.CTkSwitch(r, text=_("Girar a câmera sozinha quando desviar"),
                                         command=self._save_auto_camera)
        self.auto_camera.pack(side="left")
        if cfg.get("auto_camera", True):
            self.auto_camera.select()
        hint(box, _("Antes de pausar, tenta arrastar a câmera de volta (botão direito) sozinha; "
                  "só pausa esperando você se não conseguir."))

        box = section(scroll, _("Barra do minigame"))
        r = row(box)
        ctk.CTkButton(r, text=_("Ajustar área"), width=130, command=app.pick_scan_area).pack(side="left")
        ctk.CTkLabel(r, text=_("onde aparece a barra vertical"), text_color=MUTED).pack(side="left", padx=10)

        box = section(scroll, _("Vara"))
        r = row(box)
        ctk.CTkLabel(r, text=_("Tecla da vara")).pack(side="left")
        self.rod = ctk.CTkEntry(r, width=50, justify="center")
        self.rod.insert(0, cfg["rod_key"])
        self.rod.pack(side="left", padx=8)
        self.rod.bind("<KeyRelease>", lambda _e: self._save_rod())
        hint(box, _("A macro confere a hotbar antes de lançar e só aperta a tecla se a vara não estiver na mão."))
        r = row(box)
        self.ground = ctk.CTkSwitch(r, text=_("Se o item não vier, guardar a vara e pegar do chão"),
                                    command=self._save_ground)
        self.ground.pack(side="left")
        if cfg.get("ground_pickup", True):
            self.ground.select()

        box = section(scroll, _("Iscas"))
        r = row(box)
        self.baits_on = ctk.CTkSwitch(r, text=_("Controlar iscas (contar e trocar sozinho)"), command=self._save_baits)
        self.baits_on.pack(side="left")
        if cfg["baits"].get("enabled", True):
            self.baits_on.select()
        r = row(box)
        ctk.CTkButton(r, text=_("Conferir iscas agora"), width=150, command=app.request_bait_check).pack(side="left")
        app.number_entry(r, cfg["baits"], "recheck_at", width=50, cast=int).pack(side="right")
        ctk.CTkLabel(r, text=_("conferir quando faltarem"), text_color=MUTED).pack(side="right", padx=6)
        r = row(box)
        ctk.CTkLabel(r, text=_("Ordem")).pack(side="left")
        self.bait_order = ctk.CTkEntry(r)
        self.bait_order.insert(0, ", ".join(cfg["baits"]["order"]))
        self.bait_order.pack(side="left", fill="x", expand=True, padx=8)
        self.bait_order.bind("<KeyRelease>", lambda _e: self._save_baits())
        hint(box, _("Na 1ª vez a macro abre o menu (M → Inventory → Fishing) e conta as iscas. "
                  "Usa a primeira da ordem que você tiver; quando acabar, troca para a próxima e avisa."))

        box = section(scroll, _("Atalhos"))
        labels = {"start_stop": _("Iniciar / parar"), "set_cast_point": _("Marcar ponto"), "exit": _("Fechar macro")}
        self.hotkey_btns: dict[str, ctk.CTkButton] = {}
        for key, label in labels.items():
            r = row(box)
            ctk.CTkLabel(r, text=label).pack(side="left")
            btn = ctk.CTkButton(r, text=cfg["hotkeys"][key], width=80, fg_color="#374151",
                                command=lambda k=key: app.listen_hotkey(k))
            btn.pack(side="right")
            self.hotkey_btns[key] = btn

        box = section(scroll, _("Janela"))
        r = row(box)
        self.on_top = ctk.CTkSwitch(r, text=_("Sempre no topo"), command=self._save_on_top)
        self.on_top.pack(side="left")
        if cfg["ui"].get("always_on_top", True):
            self.on_top.select()
        r = row(box)
        self.minimize = ctk.CTkSwitch(r, text=_("Minimizar ao iniciar a pesca"), command=self._save_minimize)
        self.minimize.pack(side="left")
        if cfg["ui"].get("minimize_on_start", True):
            self.minimize.select()
        r = row(box)
        self.overlay_on = ctk.CTkSwitch(r, text=_("Overlay por cima do jogo"), command=self._save_overlay)
        self.overlay_on.pack(side="left")
        if cfg["ui"].get("overlay", True):
            self.overlay_on.select()
        ctk.CTkButton(r, text=_("Voltar para a party"), width=130, fg_color="#374151",
                      command=app.reset_overlay).pack(side="right")
        hint(box, _("Mostra tempo, peixes, itens e iscas gastas. Arraste para mudar de lugar "
                  "(com a pesca parada; pescando, os cliques passam através dele)."))
        self._build_overlay_filter(box, cfg)
        r = row(box)
        self.in_capture = ctk.CTkSwitch(r, text=_("Aparecer no Parsec / OBS"), command=self._save_in_capture)
        self.in_capture.pack(side="left")
        if cfg["ui"].get("show_in_capture", False):
            self.in_capture.select()
        hint(box, _("Desligado, a janela e o overlay somem de qualquer captura enquanto pesca (no Parsec "
                  "parece que minimizou). Ligado, aparecem; a macro se apaga dos próprios prints, então "
                  "deixe a janela no canto esquerdo, longe do meio da tela, da barra e da hotbar."))
        hint(box, _("No Roblox: desligue Screen Shake e Shift Lock, senão a câmera mexe durante a pesca."))
        self.refresh()

    def refresh(self) -> None:
        pt = self.app.cfg.get("cast_point")
        lock = _("  •  bússola ✓") if self.app.compass.ready else _("  •  bússola ✗")
        self.cast_lbl.configure(
            text=(_("x {x:.3f}  y {y:.3f}{lock}", x=pt['x'], y=pt['y'], lock=lock) if pt else _("não marcado")),
            text_color=(OK if pt else BAD))
        for key, btn in self.hotkey_btns.items():
            btn.configure(text=self.app.cfg["hotkeys"][key])

    def _save_lock(self) -> None:
        self.app.cfg["compass_lock"] = bool(self.lock.get())
        self.app.save_soon()

    def _save_auto_camera(self) -> None:
        self.app.cfg["auto_camera"] = bool(self.auto_camera.get())
        self.app.save_soon()

    def _save_baits(self) -> None:
        b = self.app.cfg["baits"]
        b["enabled"] = bool(self.baits_on.get())
        names = [n.strip() for n in self.bait_order.get().split(",") if n.strip()]
        if names:
            b["order"] = names
        self.app.save_soon()

    def _save_ground(self) -> None:
        self.app.cfg["ground_pickup"] = bool(self.ground.get())
        self.app.save_soon()

    def _save_rod(self) -> None:
        self.app.cfg["rod_key"] = self.rod.get().strip()[:10]
        self.app.save_soon()

    def _save_minimize(self) -> None:
        self.app.cfg["ui"]["minimize_on_start"] = bool(self.minimize.get())
        self.app.save_soon()

    def _save_overlay(self) -> None:
        self.app.cfg["ui"]["overlay"] = bool(self.overlay_on.get())
        self.app.apply_overlay()
        self.app.save_soon()

    def _build_overlay_filter(self, box, cfg) -> None:
        """O que aparece no overlay: partes e raridades (pedido de 25/09)."""
        ui = cfg["ui"]
        show = {**{"time": True, "fish": True, "values": True, "items": True, "baits": True},
                **ui.get("overlay_show", {})}
        visible = set(ui.get("overlay_rarities", RARITY_ORDER))
        self.overlay_parts: dict[str, ctk.CTkCheckBox] = {}
        self.overlay_rar: dict[str, ctk.CTkCheckBox] = {}
        r = row(box)
        ctk.CTkLabel(r, text=_("No overlay:"), text_color=MUTED).pack(side="left")
        for key, text in (("time", _("Tempo")), ("fish", _("Peixes")), ("values", "Yen"), ("items", _("Itens")),
                          ("baits", _("Iscas"))):
            cb = ctk.CTkCheckBox(r, text=text, width=20, checkbox_width=16, checkbox_height=16,
                                 command=self._save_overlay_filter)
            cb.pack(side="left", padx=(6, 0))
            if show.get(key, True):
                cb.select()
            self.overlay_parts[key] = cb
        r = row(box)
        short = {"legendary": "Legend."}  # a linha inteira precisa caber na janela
        for rarity in RARITY_ORDER:
            cb = ctk.CTkCheckBox(r, text=short.get(rarity, webhook.RARITY_LABELS[rarity]), width=20,
                                 checkbox_width=16,
                                 checkbox_height=16, text_color=RARITY_HEX[rarity],
                                 command=self._save_overlay_filter)
            cb.pack(side="left", padx=(6, 0))
            if rarity in visible:
                cb.select()
            self.overlay_rar[rarity] = cb

    def _save_overlay_filter(self) -> None:
        ui = self.app.cfg["ui"]
        ui["overlay_show"] = {k: bool(cb.get()) for k, cb in self.overlay_parts.items()}
        ui["overlay_rarities"] = [r for r, cb in self.overlay_rar.items() if cb.get()]
        self.app.save_soon()

    def _save_in_capture(self) -> None:
        self.app.cfg["ui"]["show_in_capture"] = bool(self.in_capture.get())
        self.app.apply_capture_mode()
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

        box = section(scroll, _("Webhook do canal"))
        r = row(box)
        self.url = ctk.CTkEntry(r, show="•", placeholder_text="https://discord.com/api/webhooks/...")
        if d["webhook_url"]:
            self.url.insert(0, d["webhook_url"])
        self.url.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text=_("ver"), width=40, fg_color="#374151", command=self._toggle_eye).pack(side="left", padx=(6, 0))
        self.url_ok = hint(box, "")
        hint(box, _("Canal → Editar → Integrações → Webhooks → Novo → Copiar URL. "
                  "O link funciona como senha: não compartilhe."))
        self.url.bind("<KeyRelease>", lambda _e: self._save())

        box = section(scroll, _("Marcar você"))
        r = row(box)
        ctk.CTkLabel(r, text=_("Seu ID do Discord")).pack(side="left")
        self.uid = ctk.CTkEntry(r, placeholder_text="ex.: 123456789012345678")
        if d["user_id"]:
            self.uid.insert(0, d["user_id"])
        self.uid.pack(side="left", fill="x", expand=True, padx=8)
        self.uid.bind("<KeyRelease>", lambda _e: self._save())
        self.uid_ok = hint(box, "")
        r = row(box)
        ctk.CTkLabel(r, text=_("Marcar em:")).pack(side="left")
        self.ping: dict[str, ctk.CTkCheckBox] = {}
        for rarity in ("mythic", "legendary", "epic"):
            cb = ctk.CTkCheckBox(r, text=webhook.RARITY_LABELS[rarity], width=20, command=self._save,
                                 fg_color=RARITY_HEX[rarity], hover_color=RARITY_HEX[rarity])
            cb.pack(side="left", padx=6)
            if rarity in d["ping_rarities"]:
                cb.select()
            self.ping[rarity] = cb

        box = section(scroll, _("Mensagens"))
        r = row(box)
        ctk.CTkLabel(r, text=_("Item com total em toda mensagem")).pack(side="left")
        self.tracked = ctk.CTkEntry(r, width=110)
        self.tracked.insert(0, d["tracked_item"])
        self.tracked.pack(side="right")
        self.tracked.bind("<KeyRelease>", lambda _e: self._save())
        r = row(box)
        self.send_img = ctk.CTkSwitch(r, text=_("Mandar print do item"), command=self._save)
        self.send_img.pack(side="left")
        if d["send_image"]:
            self.send_img.select()
        r = row(box)
        self.problems = ctk.CTkSwitch(r, text=_("Avisar quando a macro parar sozinha"), command=self._save)
        self.problems.pack(side="left")
        if d["notify_problems"]:
            self.problems.select()
        r = row(box)
        ctk.CTkButton(r, text=_("Testar envio"), command=app.test_discord).pack(side="left")
        self._validate()

    def _toggle_eye(self) -> None:
        self.url.configure(show="" if self.url.cget("show") else "•")

    def _validate(self) -> None:
        url, uid = self.url.get().strip(), self.uid.get().strip()
        if not url:
            self.url_ok.configure(text=_("Sem webhook: nada será enviado."), text_color=MUTED)
        elif webhook.valid_webhook(url):
            self.url_ok.configure(text=_("Link válido ✓"), text_color=OK)
        else:
            self.url_ok.configure(text=_("Esse link não parece um webhook do Discord."), text_color=BAD)
        if not uid:
            self.uid_ok.configure(text=_("Sem ID: ninguém é marcado."), text_color=MUTED)
        elif webhook.valid_user_id(uid):
            self.uid_ok.configure(text=_("ID válido ✓"), text_color=OK)
        else:
            self.uid_ok.configure(text=_("O ID tem só números (Modo desenvolvedor → Copiar ID)."), text_color=BAD)

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


LANGUAGE_REOPEN_WARNING = "Reabra a macro para trocar o idioma / Reopen the macro to change the language"


# ---------------------------------------------------------------- Avançado
class AdvancedTab:
    def __init__(self, app: "App", parent, on_reset: Callable[[], None]) -> None:
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.app = app
        self._build_language(scroll)
        titles = {"timings": _("Tempos"), "limits": _("Limites de segurança"), "tracking": _("Minigame")}
        for group, fields in ADVANCED_FIELDS.items():
            box = section(scroll, titles[group])
            for key, label, tip in fields:
                r = row(box)
                ctk.CTkLabel(r, text=_(label)).pack(side="left")
                cast = int if group == "limits" else float
                app.number_entry(r, app.cfg[group], key, width=70, cast=cast).pack(side="right")
                hint(box, _(tip))
        box = section(scroll, _("Diagnóstico"))
        r = row(box)
        self.diagnostic = ctk.CTkSwitch(r, text=_("Modo diagnóstico (log detalhado e prints dos problemas)"),
                                        command=self._save_diagnostic)
        self.diagnostic.pack(side="left")
        if app.cfg.get("diagnostic", False):
            self.diagnostic.select()
        hint(box, _("Deixa a macro mais pesada: ligue só quando for investigar um problema. Os prints "
                  "ficam em logs/evidencias."))
        ctk.CTkButton(scroll, text=_("Restaurar padrões"), fg_color="#374151", command=on_reset).pack(pady=10)

    def _build_language(self, scroll) -> None:
        box = section(scroll, _("Idioma / Language"))
        self.language = ctk.StringVar(value=self.app.cfg["ui"].get("language", "pt"))
        for value, text in (("pt", "Português"), ("en", "English")):
            ctk.CTkRadioButton(row(box), text=text, variable=self.language, value=value,
                               command=self._save_language).pack(side="left")
        hint(box, LANGUAGE_REOPEN_WARNING)

    def _save_language(self) -> None:
        self.app.cfg["ui"]["language"] = self.language.get()
        self.app.save_soon()
        self.app.set_status(LANGUAGE_REOPEN_WARNING)

    def _save_diagnostic(self) -> None:
        self.app.cfg["diagnostic"] = bool(self.diagnostic.get())
        logbook.set_diagnostic(self.app.cfg["diagnostic"])
        self.app.save_soon()
