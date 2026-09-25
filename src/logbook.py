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
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 2
MAX_EVIDENCE = 200
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(module)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_evidence_dir: Path | None = None
_handler: logging.Handler | None = None
# Modo diagnóstico: log detalhado (DEBUG) e prints dos problemas. Desligado a macro fica mais leve.
_diagnostic = False
_lock = threading.Lock()


def setup(log_dir: Path) -> logging.Logger:
    """Liga o log em arquivo (com rotação) e captura erros não tratados."""
    global _evidence_dir, _handler
    log_dir.mkdir(parents=True, exist_ok=True)
    _evidence_dir = log_dir / "evidencias"
    logger = logging.getLogger(LOG_NAME)
    if not logger.handlers:
        handler = RotatingFileHandler(log_dir / "macro.log", maxBytes=MAX_BYTES,
                                      backupCount=BACKUPS, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        handler.setLevel(logging.DEBUG if _diagnostic else logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        _handler = handler

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


def set_diagnostic(on: bool) -> None:
    """Liga/desliga o log detalhado e os prints dos problemas."""
    global _diagnostic
    _diagnostic = bool(on)
    if _handler is not None:
        _handler.setLevel(logging.DEBUG if _diagnostic else logging.INFO)


def save_evidence(img: np.ndarray | None, reason: str) -> Path | None:
    """Salva um print do jogo para investigar depois (só no modo diagnóstico). Nunca derruba a macro."""
    if img is None or _evidence_dir is None or not _diagnostic:
        return None
    try:
        path = _save_png(_evidence_dir, img, reason, MAX_EVIDENCE)
        get().info("Print salvo: %s", path.name)
        return path
    except (OSError, cv2.error) as exc:
        get().warning("Não consegui salvar o print (%s): %s", reason, exc)
        return None

