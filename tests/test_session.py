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
