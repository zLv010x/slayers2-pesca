import threading
import time
from datetime import datetime

import webhook
from webhook import DiscordNotifier, LootReport, build_payload, valid_user_id, valid_webhook

UID = "123456789012345678"
VALID_URL = "https://discord.com/api/webhooks/123/abc-DEF_9"


def _report(rarity="rare", image=None):
    return LootReport("Golden Fish", 1, rarity, 7, 2, "Ore", 5, "12m 03s", image)


def test_valida_link_do_webhook():
    assert valid_webhook("https://discord.com/api/webhooks/123/abc-DEF_9")
    assert not valid_webhook("https://exemplo.com/api/webhooks/123/abc")
    assert not valid_webhook("")


def test_valida_id_do_usuario():
    assert valid_user_id(UID)
    assert not valid_user_id("@fulano")


def test_item_comum_nao_marca_ninguem():
    p = build_payload(_report("rare"), UID, {"mythic"}, datetime.now())
    assert "content" not in p
    assert p["allowed_mentions"] == {"parse": []}
    campos = {f["name"]: f["value"] for f in p["embeds"][0]["fields"]}
    assert campos["Ore total"] == "5"
    assert campos["Tempo rodando"] == "12m 03s"


def test_mythic_marca_o_usuario():
    p = build_payload(_report("mythic"), UID, {"mythic"}, datetime.now())
    assert p["content"].startswith(f"<@{UID}>")
    assert p["allowed_mentions"] == {"users": [UID]}


def test_imagem_vai_como_anexo():
    import numpy as np
    p = build_payload(_report(image=np.zeros((4, 4, 3), np.uint8)), "", {"mythic"}, datetime.now())
    assert p["embeds"][0]["image"]["url"] == "attachment://item.png"


def test_avisa_quando_e_novo_no_catalogo():
    r = LootReport("Coral", 1, "common", 1, 1, "", 0, "1m 00s", None, first_in_catalog=True)
    p = build_payload(r, "", {"mythic"}, datetime.now())
    assert "catálogo" in p["embeds"][0]["description"]


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_worker_sobrevive_a_erro_inesperado_e_continua_processando(monkeypatch):
    """Um erro que não é RuntimeError (ex.: JSON inválido no 429) não pode matar a thread:
    senão a fila cresce para sempre e nada mais é avisado no Discord a noite toda."""
    calls = []

    def fake_post(url, payload, png=None):
        calls.append(payload)
        if len(calls) == 1:
            raise ValueError("corpo do 429 não é JSON válido")

    monkeypatch.setattr(webhook, "post", fake_post)
    n = DiscordNotifier()
    n.url = VALID_URL
    n.send_text("primeiro")
    n.send_text("segundo")
    assert _wait_for(lambda: len(calls) == 2)


def test_on_error_e_avisado_do_erro_inesperado(monkeypatch):
    monkeypatch.setattr(webhook, "post", lambda *a, **kw: (_ for _ in ()).throw(ValueError("boom")))
    erros = []
    n = DiscordNotifier(on_error=erros.append)
    n.url = VALID_URL
    n.send_text("oi")
    assert _wait_for(lambda: bool(erros))


def test_fila_descarta_o_mais_antigo_quando_enche(monkeypatch):
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)  # não deixa a thread consumir
    n = DiscordNotifier()
    n.url = VALID_URL
    for i in range(webhook.MAX_QUEUE + 5):
        n._enqueue((n.url, {"i": i}, None))
    assert n._queue.qsize() == webhook.MAX_QUEUE
    first = n._queue.get_nowait()
    assert first[1]["i"] == 5  # os 5 mais antigos foram descartados


def test_total_do_item_acompanhado_mostra_de_onde_vem():
    """Pedido de 24/09: 'Ore total' soma Ore + Refinement Ore e mostra quanto de cada."""
    r = LootReport("Refinement Ore", 1, "rare", 9, 2, "Ore", 3, "5m 00s", None,
                   tracked_detail="Refinement Ore 2 • Ore 1")
    field = next(f for f in build_payload(r, "", {"mythic"}, datetime.now())["embeds"][0]["fields"]
                 if f["name"] == "Ore total")
    assert field["value"] == "3 (Refinement Ore 2 • Ore 1)"
