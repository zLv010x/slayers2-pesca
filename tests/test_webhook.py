from datetime import datetime

from webhook import LootReport, build_payload, valid_user_id, valid_webhook

UID = "123456789012345678"


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
