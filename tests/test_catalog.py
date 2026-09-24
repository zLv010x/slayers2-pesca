import json

import numpy as np
import pytest

from catalog import Catalog

IMG = np.zeros((20, 60, 3), np.uint8)


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "catalogo", tmp_path / "catalogo_local"


def _index(folder):
    return json.loads((folder / "itens.json").read_text(encoding="utf-8"))["items"]


def test_item_desconhecido_vai_para_o_local_com_uma_imagem_so(dirs):
    shared, local = dirs
    cat = Catalog(shared, local)
    first = cat.record("Coral", "common", IMG)
    again = cat.record("Coral", "common", IMG)
    assert first.first_time and not again.first_time
    assert len(list((local / "imagens").glob("*.png"))) == 1
    assert _index(local)[0]["count"] == 2
    assert not (shared / "itens.json").exists()  # o compartilhado não é mexido pescando


def test_item_do_compartilhado_nao_e_novo_nem_duplica_imagem(dirs):
    shared, local = dirs
    mine = Catalog(shared, local)
    mine.record("Golden Fish", "rare", IMG)
    mine.publish()
    # PC do amigo: tem o compartilhado, catálogo local vazio
    friend = Catalog(shared, local.with_name("amigo_local"))
    assert friend.knows("Golden Fish")
    rec = friend.record("Golden Fish", "rare", IMG)
    assert not rec.first_time
    assert not (local.with_name("amigo_local") / "imagens").exists()


def test_amigo_adiciona_o_que_falta_no_local_dele(dirs):
    shared, local = dirs
    mine = Catalog(shared, local)
    mine.record("Golden Fish", "rare", IMG)
    mine.publish()
    friend_local = local.with_name("amigo_local")
    friend = Catalog(shared, friend_local)
    rec = friend.record("Black Dragon Armour", "mythic", IMG)
    assert rec.first_time
    assert [e["name"] for e in _index(friend_local)] == ["Black Dragon Armour"]


def test_corrige_erro_do_ocr_pelo_nome_conhecido(dirs):
    cat = Catalog(*dirs)
    cat.record("Golden Fish", "rare", IMG)
    rec = cat.record("Golden Fisn", "rare", IMG)
    assert rec.name == "Golden Fish" and rec.corrected and not rec.first_time
    assert cat.resolve("Golden Fisn") == "Golden Fish"


def test_nao_confunde_nomes_curtos_parecidos(dirs):
    cat = Catalog(*dirs)
    cat.record("Ore", "common", IMG)
    rec = cat.record("Core", "rare", IMG)
    assert rec.name == "Core" and rec.first_time


def test_raridade_mais_vista_vence_leitura_errada_da_cor(dirs):
    cat = Catalog(*dirs)
    cat.record("Crustadon", "legendary", IMG)
    cat.record("Crustadon", "legendary", IMG)
    assert cat.record("Crustadon", "rare", IMG).rarity == "legendary"


def test_publicar_junta_no_compartilhado_sem_contar_em_dobro(dirs):
    shared, local = dirs
    cat = Catalog(shared, local)
    cat.record("Zebra Fish", "rare", IMG)
    cat.record("Zebra Fisn", "rare", IMG)
    assert cat.publish() == ["Zebra Fish"]
    item = _index(shared)[0]
    assert item["rarity_votes"] == {"rare": 2}
    assert item["aliases"] == ["Zebra Fisn"]
    assert (shared / item["image"]).exists()
    assert "count" not in item  # contagem é pessoal, não vai para o compartilhado
    assert cat.publish() == []  # publicar de novo não duplica nada
    assert _index(shared)[0]["rarity_votes"] == {"rare": 2}


def test_indice_sobrevive_a_reabrir(dirs):
    Catalog(*dirs).record("Zebra Fish", "rare", IMG)
    assert Catalog(*dirs).resolve("zebra fish") == "Zebra Fish"


def test_erro_ao_salvar_indice_local_nao_derruba_o_registro(dirs, monkeypatch):
    """Disco travado (OneDrive/antivírus) não pode abortar o record() antes do Discord ser avisado."""
    import catalog as catalog_mod
    cat = Catalog(*dirs)
    monkeypatch.setattr(catalog_mod, "_save_index", lambda path, items: (_ for _ in ()).throw(OSError("travado")))
    rec = cat.record("Coral", "common", IMG)
    assert rec.name == "Coral" and rec.first_time
