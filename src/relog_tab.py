"""Aba Relog: ligar o auto relog, o gamepass de spawn e para qual servidor voltar."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

import config
import relog_bridge
from i18n import _
from tabs import AMBER, BAD, MUTED, OK, hint, row, section

if TYPE_CHECKING:
    from app import App

TONE_COLOR = {"ok": OK, "warn": AMBER, "bad": BAD, "off": MUTED}
SERVER_HINTS = {
    "vip": "Com VIP: clica no mundo e segura o JOIN (ele vira JOIN PRIVATE) para abrir o seu servidor privado.",
    "nick": "Sem VIP: digita o nick exato do dono do servidor, aperta Enter e clica em Join Private.",
}
NICK_MAX = 40


def status_line(cfg: dict) -> tuple[str, str]:
    """Texto e tom ("ok", "warn", "bad", "off") do estado do auto relog."""
    if not cfg.get("relog", {}).get("enabled"):
        return _("Desligado: se o jogo cair, a pesca para e espera você."), "off"
    reason = relog_bridge.not_ready_reason(cfg)
    if reason is None:
        return _("✓ Pronto: se o jogo cair, reconecta e volta a pescar sozinho."), "ok"
    if reason == relog_bridge.SPAWN_NOT_SET:
        return (_("Falta setar o spawn: inicie a pesca no ponto de pesca que a macro seta sozinha "
                "depois do 1º peixe (ou use o botão \"Setar spawn agora\")."), "warn")
    return _("Não vai reconectar: {reason}.", reason=_(reason)), "bad"


class RelogTab:
    def __init__(self, app: "App", parent) -> None:
        self.app = app
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        self.state = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=12, weight="bold"),
                                  justify="left", anchor="w", wraplength=360)
        self.state.pack(fill="x", padx=6, pady=(6, 0))
        self._build_switch(scroll)
        self._build_spawn(scroll)
        self._build_server(scroll)
        self._load()
        self._refresh()

    # ------------------------------------------------------------ montagem
    def _build_switch(self, scroll) -> None:
        box = section(scroll, _("Auto relog"))
        self.enabled = ctk.CTkSwitch(row(box), text=_("Reconectar sozinho se o jogo cair"), command=self._save)
        self.enabled.pack(side="left")
        hint(box, _("Quando cair (menu do jogo ou 'Disconnected'): Reconnect → PLAY → mundo → servidor "
                  "privado → nasce no spawn setado e volta a pescar. Se a conta entrar em outro PC "
                  "(erro 264), não reconecta."))
        r = row(box)
        ctk.CTkLabel(r, text=_("Reconexões por hora (máx.)")).pack(side="left")
        self.app.number_entry(r, self.app.cfg["relog"], "max_per_hour", width=50, cast=int).pack(side="right")
        for key, text in (("step_timeout_sec", _("Espera máx. por passo (s)")),
                          ("loading_timeout_sec", _("Espera máx. carregando o jogo (s)"))):
            r = row(box)
            ctk.CTkLabel(r, text=text).pack(side="left")
            self.app.number_entry(r, self.app.cfg["relog"], key, width=60).pack(side="right")
        hint(box, _("Cada PC demora um tanto para carregar: aumente se o seu for mais lento."))

    def _build_spawn(self, scroll) -> None:
        box = section(scroll, _("Gamepass Set Spawn"))
        self.gamepass = ctk.CTkCheckBox(row(box), text=_("Tenho o gamepass Set Spawn"), command=self._save)
        self.gamepass.pack(side="left")
        hint(box, _("Obrigatório para o relog: depois de reconectar o personagem nasce no spawn. "
                  "Sem o gamepass ele nasceria longe do ponto de pesca."))
        self.spawn_set = ctk.CTkCheckBox(row(box), text=_("Já setei o spawn no ponto de pesca"), command=self._save)
        self.spawn_set.pack(side="left")
        r = row(box)
        self.spawn_btn = ctk.CTkButton(r, text=_("Setar spawn agora"), width=150, command=self.app.request_set_spawn)
        self.spawn_btn.pack(side="left")
        ctk.CTkLabel(r, text=_("fique no ponto de pesca"), text_color=MUTED).pack(side="left", padx=6)
        hint(box, _("Se não estiver setado, a macro seta sozinha depois do 1º peixe "
                  "(Commands → digita set → Enter → ✓ verde)."))

    def _build_server(self, scroll) -> None:
        box = section(scroll, _("Servidor para voltar"))
        self.mode = ctk.StringVar(value="vip")
        for value, text in (("vip", _("Tenho VIP (volto para o meu servidor privado)")),
                            ("nick", _("Não tenho VIP (entro no servidor de outra pessoa)"))):
            ctk.CTkRadioButton(row(box), text=text, variable=self.mode, value=value,
                               command=self._save).pack(side="left")
        r = row(box)
        ctk.CTkLabel(r, text=_("Nick do dono")).pack(side="left")
        self.nick = ctk.CTkEntry(r, placeholder_text=_("nick exato de quem tem o servidor"))
        self.nick.pack(side="left", fill="x", expand=True, padx=8)
        self.nick.bind("<KeyRelease>", lambda _e: self._save())
        self.server_hint = hint(box, "")
        r = row(box)
        ctk.CTkLabel(r, text=_("Mundo")).pack(side="left")
        self.world = ctk.CTkEntry(r, width=140)
        self.world.pack(side="left", padx=8)
        self.world.bind("<KeyRelease>", lambda _e: self._save())
        ctk.CTkLabel(r, text=_("card clicado na lista de servidores"), text_color=MUTED).pack(side="left")

    # ------------------------------------------------------------ estado
    def _load(self) -> None:
        rc = self.app.cfg["relog"]
        for widget, key in ((self.enabled, "enabled"), (self.gamepass, "has_spawn_gamepass"),
                            (self.spawn_set, "spawn_set")):
            if rc.get(key):
                widget.select()
        self.mode.set("nick" if rc.get("server_mode") == "nick" else "vip")
        if rc.get("owner_nick"):
            self.nick.insert(0, rc["owner_nick"])
        self.world.insert(0, rc.get("map_name") or config.DEFAULTS["relog"]["map_name"])

    def _save(self) -> None:
        rc = self.app.cfg["relog"]
        rc["enabled"] = bool(self.enabled.get())
        rc["has_spawn_gamepass"] = bool(self.gamepass.get())
        rc["spawn_set"] = bool(self.spawn_set.get())
        rc["server_mode"] = self.mode.get()
        rc["owner_nick"] = self.nick.get().strip()[:NICK_MAX]
        rc["map_name"] = self.world.get().strip() or config.DEFAULTS["relog"]["map_name"]
        self._refresh()
        self.app.save_soon()

    def _refresh(self) -> None:
        text, tone = status_line(self.app.cfg)
        self.state.configure(text=text, text_color=TONE_COLOR[tone])
        has_pass = bool(self.gamepass.get())
        for widget in (self.spawn_set, self.spawn_btn):
            widget.configure(state="normal" if has_pass else "disabled")
        is_nick = self.mode.get() == "nick"
        self.nick.configure(state="normal" if is_nick else "disabled")
        self.server_hint.configure(text=_(SERVER_HINTS["nick" if is_nick else "vip"]))

    def sync(self) -> None:
        """Marca "Já setei o spawn" depois que a macro setou sozinha."""
        if self.app.cfg["relog"].get("spawn_set"):
            self.spawn_set.select()
        self._refresh()
