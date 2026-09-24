"""Diário da macro: tudo o que acontece vai para logs/macro.log.

Quando algo dá errado, um print do jogo vai para logs/evidencias/, para dar
para ver depois exatamente o que estava na tela.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
import numpy as np

LOG_NAME = "pesca"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5
MAX_EVIDENCE = 200
MAX_MINIGAME_FRAMES = 300
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(module)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_evidence_dir: Path | None = None
_lock = threading.Lock()


def setup(log_dir: Path) -> logging.Logger:
    """Liga o log em arquivo (com rotação) e captura erros não tratados."""
    global _evidence_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    _evidence_dir = log_dir / "evidencias"
    logger = logging.getLogger(LOG_NAME)
    if not logger.handlers:
        handler = RotatingFileHandler(log_dir / "macro.log", maxBytes=MAX_BYTES,
                                      backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    def excepthook(exc_type, exc, tb):
        logger.critical("Erro não tratado", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args):
        logger.critical("Erro não tratado na thread %s", args.thread.name if args.thread else "?",
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return logger


def get() -> logging.Logger:
    return logging.getLogger(LOG_NAME)


def _save_png(folder: Path, img: np.ndarray, reason: str, keep: int) -> Path:
    with _lock:
        folder.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")[:40] or "print"
        path = folder / f"{datetime.now():%Y%m%d-%H%M%S}_{slug}.png"
        cv2.imwrite(str(path), img)
        for extra in sorted(folder.glob("*.png"))[:-keep]:
            extra.unlink(missing_ok=True)
    return path


def save_evidence(img: np.ndarray | None, reason: str) -> Path | None:
    """Salva um print do jogo para investigar depois. Nunca derruba a macro."""
    if img is None or _evidence_dir is None:
        return None
    try:
        path = _save_png(_evidence_dir, img, reason, MAX_EVIDENCE)
        get().info("Print salvo: %s", path.name)
        return path
    except (OSError, cv2.error) as exc:
        get().warning("Não consegui salvar o print (%s): %s", reason, exc)
        return None



def save_minigame_frame(img: np.ndarray, reading, holding: bool) -> None:
    """Recorte da barra durante o minigame, com o que a macro leu no nome do arquivo."""
    if _evidence_dir is None:
        return
    if reading is None:
        tag = "sem-leitura"
    else:
        zone = f"zona{reading.zone_top}-{reading.zone_bot}" if reading.has_zone else "sem-zona"
        tag = f"quadrado{int(reading.ball_y)}-{zone}"
    tag += "-segurando" if holding else "-solto"
    try:
        _save_png(_evidence_dir.parent / "minigame", img, tag, MAX_MINIGAME_FRAMES)
    except (OSError, cv2.error) as exc:
        get().warning("Não consegui salvar o recorte do minigame: %s", exc)


def export_bundle(root: Path, dest_dir: Path) -> Path:
    """ZIP com tudo que ajuda a achar bugs, SEM segredos (link do webhook e ID ficam de fora)."""
    import json
    import zipfile

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"slayers2-logs-{datetime.now():%Y%m%d-%H%M}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in ("logs",):
            for f in (root / folder).rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(root))
        for rel in ("calibracao/iscas.json", "catalogo_local/itens.json"):
            if (root / rel).exists():
                z.write(root / rel, rel)
        cfg_path = root / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                discord = cfg.get("discord", {})
                for secret in ("webhook_url", "user_id"):
                    if discord.get(secret):
                        discord[secret] = "(removido)"
                z.writestr("config_sem_segredos.json", json.dumps(cfg, indent=2, ensure_ascii=False))
            except (OSError, ValueError):
                pass
    return out
