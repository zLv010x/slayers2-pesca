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
                    s.recent(None)
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
    assert len(s.recent(None)) == 4           # sem filtro = mostra tudo
    assert s.recent(set()) == []              # todas as raridades desligadas = nada
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


def test_desligar_raridades_esconde_mas_nao_perde_os_drops():
    """Pedido de 24/09: desligou tudo menos mythic, voltou a pescar e esqueceu: os drops
    escondidos continuam guardados e aparecem quando a raridade é ligada de novo."""
    s = Session()
    visible = {"mythic"}
    s.record("Coral", 1, "common")
    s.record("Ore", 1, "mythic")
    s.record("Clown Fish", 1, "rare")
    assert [n for _, n, _, _ in s.recent(visible)] == ["Ore"]
    assert [n for _, n, _, _ in s.recent(visible | {"rare", "common"})] == ["Clown Fish", "Ore", "Coral"]


def test_historico_guarda_a_noite_inteira():
    """Antes guardava só os 500 últimos: numa noite (~2000 drops) os mythic antigos sumiam."""
    s = Session()
    s.record("Ore", 1, "mythic")
    for _ in range(3000):
        s.record("Coral", 1, "common")
    assert [n for _, n, _, _ in s.recent({"mythic"})] == ["Ore"]


def test_ore_conta_so_o_item_ore():
    """Pedido de 24/09: Refinement Ore (rare) e Ore (mythic) são itens diferentes."""
    s = Session()
    for name in ("Refinement Ore", "Refinement Ore", "Ore", "ore"):
        s.record(name, 1, "rare")
    assert s.total_of("Ore") == 2


# ---------------------------------------------------------------- guardar até resetar (24/09)
def test_sessao_continua_depois_de_fechar_e_abrir(tmp_path, monkeypatch):
    """Pedido de 24/09: guarda tudo (histórico, contagens, tempo, iscas) até clicar em Resetar."""
    import session as mod
    agora = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: agora[0])
    state = tmp_path / "sessao-atual.json"
    s = Session(log_dir=tmp_path, state_path=state)
    s.start()
    s.record("Ore", 1, "mythic")
    s.record("Coral", 1, "common")
    s.record_miss()
    s.record_bait("Worm")
    agora[0] = 160.0
    s.pause()
    again = Session.load(log_dir=tmp_path, state_path=state)
    assert [n for _, n, _, _ in again.recent(None)] == ["Coral", "Ore"]
    assert again.total_of("Ore") == 1 and again.catches == 2 and again.misses == 1
    assert again.rarities == {"mythic": 1, "common": 1} and again.baits_used == {"Worm": 1}
    assert again.elapsed_seconds() == 60
    again.record("Coral", 1, "common")  # continua no mesmo CSV
    assert len(list(tmp_path.glob("sessao-*.csv"))) == 1


def test_resetar_apaga_o_que_foi_guardado(tmp_path):
    state = tmp_path / "sessao-atual.json"
    s = Session(log_dir=tmp_path, state_path=state)
    s.record("Ore", 1, "mythic")
    assert state.exists()
    s.forget()
    assert not state.exists()
    fresh = Session.load(log_dir=tmp_path, state_path=state)
    assert fresh.catches == 0 and fresh.recent(None) == []


def test_arquivo_guardado_estragado_comeca_do_zero(tmp_path):
    state = tmp_path / "sessao-atual.json"
    state.write_text("{isso não é json", encoding="utf-8")
    s = Session.load(log_dir=tmp_path, state_path=state)
    assert s.catches == 0
    assert (tmp_path / "sessao-atual.json.bak").exists()  # guarda o estragado para conferir


def test_falha_ao_guardar_nao_derruba_o_registro(tmp_path, monkeypatch):
    import session as mod
    s = Session(log_dir=tmp_path, state_path=tmp_path / "sessao-atual.json")
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("travado")))
    s.record("Ore", 1, "mythic")
    assert s.catches == 1


def test_lembra_a_raridade_de_cada_item_mesmo_depois_de_reabrir(tmp_path):
    state = tmp_path / "sessao-atual.json"
    s = Session(log_dir=tmp_path, state_path=state)
    s.record("Ore", 1, "mythic")
    s.record("Coral", 1, "common")
    assert s.item_rarities() == {"Ore": "mythic", "Coral": "common"}
    assert Session.load(log_dir=tmp_path, state_path=state).item_rarities() == {"Ore": "mythic", "Coral": "common"}
