import sys
import threading

from session import Session, format_elapsed


def test_record_e_total_of_em_threads_diferentes_nao_derruba(tmp_path):
    """A pesca grava itens numa thread enquanto a interface lê a cada 1s (SessionTab.refresh):
    não pode dar RuntimeError de dicionário mudando de tamanho durante a leitura."""
    original = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)  # força troca de thread com muito mais frequência
    try:
        s = Session(log_dir=tmp_path)
        errors = []

        def escrever():
            for i in range(3000):
                s.record(f"Item {i}", 1, "common")

        def ler():
            for _ in range(3000):
                try:
                    s.total_of("Item 1")
                    s.recent(set())
                except RuntimeError as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=escrever)
        t2 = threading.Thread(target=ler)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert errors == []
    finally:
        sys.setswitchinterval(original)


def test_erro_ao_gravar_csv_nao_derruba_o_registro(tmp_path):
    """Se o disco falhar (OneDrive/antivírus travando o arquivo), o item não pode se perder:
    a contagem da sessão precisa continuar valendo mesmo sem conseguir gravar o CSV."""
    s = Session(log_dir=tmp_path)

    class BoomPath:
        def open(self, *a, **kw):
            raise OSError("arquivo travado")

    s._csv_path = BoomPath()
    s.record("Ore", 1, "common")  # não pode levantar
    assert s.catches == 1 and s.total_of("ore") == 1


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


def test_config_antigo_com_20s_vira_10s(tmp_path):
    import json
    import config
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"timings": {"minigame_start_timeout_sec": 20.0}}), encoding="utf-8")
    assert config.load(p)["timings"]["minigame_start_timeout_sec"] == 10.0
    # quem escolheu outro valor mantém o seu
    p.write_text(json.dumps({"timings": {"minigame_start_timeout_sec": 15.0}}), encoding="utf-8")
    assert config.load(p)["timings"]["minigame_start_timeout_sec"] == 15.0


def test_filtro_do_historico_por_raridade():
    s = Session()
    s.record("Coral", 1, "common")
    s.record("Black Dragon Armour", 1, "mythic")
    s.record("Golden Fish", 1, "rare")
    s.record("Flame Scarf", 1, "mythic")
    assert [n for _, n, _, _ in s.recent({"mythic"})] == ["Flame Scarf", "Black Dragon Armour"]
    assert [n for _, n, _, _ in s.recent({"mythic", "rare"})] == ["Flame Scarf", "Golden Fish", "Black Dragon Armour"]
    assert len(s.recent(set())) == 4          # nada selecionado = mostra tudo
    assert s.recent({"legendary"}) == []


def test_historico_guarda_itens_antigos_para_o_filtro():
    s = Session()
    s.record("Black Dragon Armour", 1, "mythic")
    for _ in range(200):
        s.record("Coral", 1, "common")
    assert [n for _, n, _, _ in s.recent({"mythic"})] == ["Black Dragon Armour"]


def test_iscas_gastas_por_tipo_e_snapshot_e_copia():
    s = Session()
    s.record_bait("Worm")
    s.record_bait("Worm")
    s.record_bait("Fish Head")
    s.record("Clown Fish", 2, "rare")
    elapsed, counts, baits = s.overlay_snapshot()
    assert baits == {"Worm": 2, "Fish Head": 1}
    assert counts == {"Clown Fish": 2}
    assert elapsed == s.elapsed_text()
    counts["Clown Fish"] = 99
    baits["Worm"] = 99
    assert s.counts["Clown Fish"] == 2 and s.baits_used["Worm"] == 2
