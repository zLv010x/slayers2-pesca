import json

import numpy as np

from catalog import Catalog

IMG = np.zeros((20, 60, 3), np.uint8)


def test_primeira_vez_salva_uma_imagem_so(tmp_path):
    cat = Catalog(tmp_path)
    first = cat.record("Coral", "common", IMG)
    again = cat.record("Coral", "common", IMG)
    assert first.first_time and not again.first_time
    assert len(list((tmp_path / "imagens").glob("*.png"))) == 1
    data = json.loads((tmp_path / "itens.json").read_text(encoding="utf-8"))
    assert data["items"][0]["count"] == 2
    assert data["items"][0]["image"] == "imagens/coral.png"


def test_corrige_erro_do_ocr_pelo_nome_conhecido(tmp_path):
    cat = Catalog(tmp_path)
    cat.record("Golden Fish", "rare", IMG)
    rec = cat.record("Golden Fisn", "rare", IMG)
    assert rec.name == "Golden Fish" and rec.corrected
    assert cat.resolve("Golden Fisn") == "Golden Fish"
    # a leitura errada vira apelido, então da próxima vez é reconhecida direto
    assert "Golden Fisn" in cat.items["goldenfish"]["aliases"]


def test_nao_confunde_nomes_curtos_parecidos(tmp_path):
    cat = Catalog(tmp_path)
    cat.record("Ore", "common", IMG)
    rec = cat.record("Core", "rare", IMG)
    assert rec.name == "Core" and rec.first_time


def test_raridade_mais_vista_vence_leitura_errada_da_cor(tmp_path):
    cat = Catalog(tmp_path)
    cat.record("Crustadon", "legendary", IMG)
    cat.record("Crustadon", "legendary", IMG)
    rec = cat.record("Crustadon", "rare", IMG)  # cor lida errado uma vez
    assert rec.rarity == "legendary"


def test_indice_sobrevive_a_reabrir(tmp_path):
    Catalog(tmp_path).record("Zebra Fish", "rare", IMG)
    cat = Catalog(tmp_path)
    assert cat.resolve("zebra fish") == "Zebra Fish"
