"""Macro mais leve (25/09): prints de problema e log detalhado só no modo diagnóstico."""
import logging

import numpy as np

import logbook

IMG = np.zeros((20, 30, 3), np.uint8)


def test_sem_diagnostico_nao_salva_print(tmp_path, monkeypatch):
    monkeypatch.setattr(logbook, "_evidence_dir", tmp_path)
    logbook.set_diagnostic(False)
    assert logbook.save_evidence(IMG, "sem aviso de item") is None
    assert list(tmp_path.iterdir()) == []


def test_com_diagnostico_salva_print(tmp_path, monkeypatch):
    monkeypatch.setattr(logbook, "_evidence_dir", tmp_path)
    logbook.set_diagnostic(True)
    try:
        path = logbook.save_evidence(IMG, "sem aviso de item")
        assert path is not None and path.exists()
    finally:
        logbook.set_diagnostic(False)


def test_log_detalhado_so_no_diagnostico(monkeypatch):
    handler = logging.Handler()
    monkeypatch.setattr(logbook, "_handler", handler)
    logbook.set_diagnostic(False)
    assert handler.level == logging.INFO
    logbook.set_diagnostic(True)
    assert handler.level == logging.DEBUG
    logbook.set_diagnostic(False)
