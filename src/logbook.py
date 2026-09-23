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
MAX_ITEM_SNAPSHOTS = 1000
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


def save_item(img: np.ndarray | None, name: str) -> None:
    """Guarda o recorte de cada item pego, para conferir se o nome foi lido certo."""
    if img is None or _evidence_dir is None:
        return
    try:
        _save_png(_evidence_dir.parent / "itens", img, name, MAX_ITEM_SNAPSHOTS)
    except (OSError, cv2.error) as exc:
        get().warning("Não consegui salvar o recorte de %s: %s", name, exc)
