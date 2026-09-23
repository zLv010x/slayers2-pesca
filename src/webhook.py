"""Envio de avisos para um canal do Discord via webhook.

O envio roda numa thread própria para nunca travar a pesca, e respeita o limite
de mensagens do Discord (resposta 429 = esperar e tentar de novo).
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np

WEBHOOK_RE = re.compile(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$")
USER_ID_RE = re.compile(r"^\d{15,21}$")

RARITY_COLORS = {
    "common": 0x9AA0A6,
    "rare": 0x3B82F6,
    "epic": 0xA855F7,
    "legendary": 0xF5B400,
    "mythic": 0xE11D48,
}
RARITY_LABELS = {
    "common": "Comum",
    "rare": "Rare",
    "epic": "Epic",
    "legendary": "Legendary",
    "mythic": "Mythic",
}
MAX_RETRIES = 3
TIMEOUT_SEC = 15
USER_AGENT = "slayers2-pesca (webhook)"


def valid_webhook(url: str) -> bool:
    return bool(WEBHOOK_RE.match(url.strip()))


def valid_user_id(user_id: str) -> bool:
    return bool(USER_ID_RE.match(user_id.strip()))


@dataclass(frozen=True)
class LootReport:
    name: str
    quantity: int
    rarity: str
    session_count: int      # quantos itens já pegou nesta sessão
    item_total: int         # quantos desse item nesta sessão
    tracked_name: str       # item acompanhado em todas as mensagens (ex.: "Ore")
    tracked_total: int      # total desse item na sessão
    elapsed: str            # tempo de macro rodando, ex.: "1h 05m"
    image: np.ndarray | None
    is_new: bool = False    # primeira vez na coleção (selo NEW! do jogo)
    first_in_catalog: bool = False  # item que o catálogo da macro ainda não conhecia


def build_payload(report: LootReport, user_id: str, ping_rarities: set[str], when: datetime) -> dict:
    rarity = report.rarity if report.rarity in RARITY_COLORS else "common"
    fields = [
        {"name": "Raridade", "value": RARITY_LABELS[rarity], "inline": True},
        {"name": "Deste item na sessão", "value": str(report.item_total), "inline": True},
        {"name": "Itens na sessão", "value": str(report.session_count), "inline": True},
    ]
    if report.tracked_name:
        fields.append({"name": f"{report.tracked_name} total", "value": str(report.tracked_total), "inline": True})
    fields.append({"name": "Tempo rodando", "value": report.elapsed, "inline": True})
    embed = {
        "title": ("🆕 " if report.is_new else "") + f"{report.name}  x{report.quantity}",
        "color": RARITY_COLORS[rarity],
        "fields": fields,
        "timestamp": when.astimezone(timezone.utc).isoformat(),
    }
    notes = []
    if report.is_new:
        notes.append("Item novo na coleção!")
    if report.first_in_catalog:
        notes.append("📖 Primeira vez no catálogo da macro.")
    if notes:
        embed["description"] = "\n".join(notes)
    if report.image is not None:
        embed["image"] = {"url": "attachment://item.png"}
    payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if rarity in ping_rarities and valid_user_id(user_id):
        uid = user_id.strip()
        payload["content"] = f"<@{uid}> pegou um **{RARITY_LABELS[rarity].upper()}**!"
        payload["allowed_mentions"] = {"users": [uid]}
    return payload


def _multipart(payload: dict, png: bytes | None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
        f"Content-Type: application/json\r\n\r\n".encode() + json.dumps(payload).encode() + b"\r\n"
    ]
    if png is not None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"item.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n".encode() + png + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post(url: str, payload: dict, png: bytes | None = None) -> None:
    """Envia agora (bloqueia). Lança RuntimeError com uma mensagem legível se falhar."""
    body, ctype = _multipart(payload, png)
    for _ in range(MAX_RETRIES):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": ctype, "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC):
                return
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry = json.loads(exc.read() or b"{}").get("retry_after", 1.0)
                time.sleep(float(retry) + 0.1)
                continue
            if exc.code in (401, 404):
                raise RuntimeError("Webhook inválido ou apagado (confira o link).") from exc
            raise RuntimeError(f"Discord recusou o envio (HTTP {exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Sem conexão com o Discord: {exc.reason}") from exc
    raise RuntimeError("Discord limitou os envios; tente de novo mais tarde.")


class DiscordNotifier:
    """Fila de envios em segundo plano. Erros vão para on_error, nunca para a pesca."""

    def __init__(self, on_error=None) -> None:
        self.url = ""
        self.user_id = ""
        self.ping_rarities: set[str] = {"mythic"}
        self._on_error = on_error or (lambda msg: None)
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    @property
    def enabled(self) -> bool:
        return valid_webhook(self.url)

    def send_loot(self, report: LootReport) -> None:
        if not self.enabled:
            return
        payload = build_payload(report, self.user_id, self.ping_rarities, datetime.now())
        png = None
        if report.image is not None:
            ok, buf = cv2.imencode(".png", report.image)
            png = buf.tobytes() if ok else None
        self._queue.put((self.url, payload, png))

    def send_text(self, text: str, ping: bool = False) -> None:
        if not self.enabled:
            return
        payload = {"content": text, "allowed_mentions": {"parse": []}}
        if ping and valid_user_id(self.user_id):
            uid = self.user_id.strip()
            payload["content"] = f"<@{uid}> {text}"
            payload["allowed_mentions"] = {"users": [uid]}
        self._queue.put((self.url, payload, None))

    def _worker(self) -> None:
        while True:
            url, payload, png = self._queue.get()
            try:
                post(url, payload, png)
            except RuntimeError as exc:
                self._on_error(str(exc))
