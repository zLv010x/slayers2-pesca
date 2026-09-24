import json
import zipfile

from logbook import export_bundle


def test_exporta_logs_sem_o_link_do_webhook(tmp_path):
    root = tmp_path / "macro"
    (root / "logs" / "evidencias").mkdir(parents=True)
    (root / "logs" / "macro.log").write_text("linha", encoding="utf-8")
    (root / "logs" / "evidencias" / "x.png").write_bytes(b"png")
    link = "https://discord.com/api/webhooks/123/segredo"
    (root / "config.json").write_text(json.dumps({"discord": {"webhook_url": link, "user_id": "123456789012345678"}}),
                                      encoding="utf-8")
    out = export_bundle(root, tmp_path / "saida")
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"logs/macro.log", "logs/evidencias/x.png", "config_sem_segredos.json"} <= names
        assert "config.json" not in names
        cfg = z.read("config_sem_segredos.json").decode("utf-8")
    assert "segredo" not in cfg and "123456789012345678" not in cfg
