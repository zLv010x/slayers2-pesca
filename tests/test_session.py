from session import Session, format_elapsed


def test_formata_tempo():
    assert format_elapsed(65) == "1m 05s"
    assert format_elapsed(3725) == "1h 02m 05s"


def test_soma_quantidade_do_aviso_nao_do_inventario(tmp_path):
    s = Session(log_dir=tmp_path)
    s.record("Ore", 1, "common")
    s.record("Golden Fish", 1, "rare")
    s.record("Ore", 1, "common")
    assert s.total_of("ore") == 2
    assert s.catches == 3
    assert s.last[0][1] == "Ore"
    linhas = next(tmp_path.glob("sessao-*.csv")).read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "hora,item,quantidade,raridade" and len(linhas) == 4


def test_tempo_so_conta_enquanto_pesca(monkeypatch):
    import session as mod
    agora = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: agora[0])
    s = Session()
    agora[0] = 400.0            # janela aberta 5 min sem pescar
    assert s.elapsed_seconds() == 0
    s.start()
    agora[0] = 460.0            # pescou 1 min
    s.pause()
    agora[0] = 1000.0           # parado: o relógio não anda
    assert s.elapsed_seconds() == 60
    s.start()
    agora[0] = 1030.0           # voltou a pescar 30 s
    assert s.elapsed_seconds() == 90
    assert s.elapsed_text() == "1m 30s"
