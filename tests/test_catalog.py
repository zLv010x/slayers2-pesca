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


def test_publicar_nao_leva_nome_lixo_para_o_compartilhado(dirs):
    # 24/09: "6d" (prazo dos códigos no menu principal) e "Collect" entraram no catálogo local
    shared, local = dirs
    cat = Catalog(shared, local)
    for name in ("6d", "Collect", "Coral"):
        cat.record(name, "common", IMG)
    assert cat.publish() == ["Coral"]
    assert [i["name"] for i in _index(shared)] == ["Coral"]


def test_plausible_name_fica_no_catalogo_e_o_loot_usa_o_mesmo():
    import catalog
    import loot
    assert loot.plausible_name is catalog.plausible_name


# ---------------------------------------------------------------- leituras erradas reais (24/09)
KNOWN = ["Clown Fish", "Golden Fish", "Zebra Fish", "Krathulon", "Crustadon", "OuwFish", "OuwFwesh",
         "Silk Thread", "Lost Cape", "Lost Lantern", "Lost Mask", "Metal Scraps", "Coral",
         "Refinement Ore", "Ore", "Sea Horse", "Squid Beanie"]


@pytest.fixture
def known(dirs):
    shared, local = dirs
    shared.mkdir(parents=True)
    items = [{"name": n, "slug": n.lower().replace(" ", "-"), "image": None, "rarity": "rare",
              "rarity_votes": {"rare": 1}, "aliases": []} for n in KNOWN]
    (shared / "itens.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    return Catalog(shared, local)


# (lido pelo OCR nos logs do usuário, do Ewerton e do Inside, nome certo)
MISREADS = [
    ("Clov.tn Fish", "Clown Fish"), ("Clovt.tn Fish", "Clown Fish"), ("Clovvn Fish", "Clown Fish"),
    ("Clov•.ifl Fish", "Clown Fish"), ("C 101,vn Fish", "Clown Fish"),
    ("Golden FEh", "Golden Fish"),
    ("Z±ra Fish", "Zebra Fish"), ("U Zebra Fish", "Zebra Fish"), ("Jzebra Fish", "Zebra Fish"),
    ("u) uzebra Fish", "Zebra Fish"), ("quebra Fish", "Zebra Fish"), ("s9zebra Fish", "Zebra Fish"),
    ("KrathLtlon", "Krathulon"), ("Krath LI lon", "Krathulon"), ("KrathLlIon", "Krathulon"),
    ("Crusta don", "Crustadon"), ("Crustadofi", "Crustadon"), ("C r Ltstadon", "Crustadon"),
    ("OuvvFish", "OuwFish"), ("Ouv.tFish", "OuwFish"), ("GNOuwFish", "OuwFish"),
    ("Ouv.rFwesh", "OuwFwesh"), ("Ouv.tFv.tesh", "OuwFwesh"), ("OuwFv.tesh", "OuwFwesh"),
    ("Ou w Fv•jesh", "OuwFwesh"),
    ("Osilk Thread", "Silk Thread"), ("LO$t Cape", "Lost Cape"), ("Lost Ca pe", "Lost Cape"),
    ("ostCa e", "Lost Cape"), ("Lest Lantern", "Lost Lantern"), ("8 N Metal Scraps", "Metal Scraps"),
    ("é-4Coral", "Coral"),
]


@pytest.mark.parametrize("read, name", MISREADS)
def test_leitura_errada_vira_o_item_certo(known, read, name):
    assert known.resolve(read) == name


# Nomes que NÃO podem virar outro item (itens diferentes de verdade ou parecidos demais)
DIFFERENT = ["OuwFwesh", "Mythic Refinement Ore", "Core", "Big Zebra Fish", "Crustadon Shell",
             "Lost Mask", "Golden Fishing Rod"]


@pytest.mark.parametrize("read", DIFFERENT)
def test_item_diferente_nao_vira_outro(known, read):
    assert known.resolve(read) == read


def test_ouwfwesh_novo_nao_vira_ouwfish(dirs):
    """24/09: OuwFwesh é um item de verdade (print "OuwFwesh x1"), não erro de OuwFish."""
    cat = Catalog(*dirs)
    cat.record("OuwFish", "common", IMG)
    assert cat.record("OuwFwesh", "common", IMG).first_time


def test_botao_collect_e_etiqueta_new_nao_sao_itens():
    import catalog
    for junk in ("Collect", "Cotlect", "lollect", "NEW!", "6d"):
        assert not catalog.plausible_name(junk), junk
    for real in ("Ore", "Coral", "Clown Fish", "Metal Scraps"):
        assert catalog.plausible_name(real), real


def _old_local(local, entries):
    """Catálogo local do jeito que a versão antiga gravava (cada leitura errada virava um item)."""
    (local / "imagens").mkdir(parents=True, exist_ok=True)
    items = []
    for name, count, votes in entries:
        slug = name.lower().replace(" ", "-").replace("!", "")
        (local / "imagens" / f"{slug}.png").write_bytes(b"png")
        items.append({"name": name, "slug": slug, "image": f"imagens/{slug}.png", "rarity": None,
                      "rarity_votes": votes, "aliases": [], "count": count,
                      "first_seen": "2026-09-23T20:00:00", "last_seen": "2026-09-24T02:00:00"})
    (local / "itens.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def test_arrumar_junta_leituras_erradas_e_tira_o_lixo(dirs):
    shared, local = dirs
    Catalog(shared, local.with_name("outro")).record("Zebra Fish", "rare", IMG)
    Catalog(shared, local.with_name("outro")).publish()
    _old_local(local, [("Zebra Fish", 5, {"rare": 5}), ("Jzebra Fish", 3, {"rare": 2, "common": 1}),
                       ("Clown Fish", 4, {"rare": 4}), ("Clovvn Fish", 1, {"common": 1}),
                       ("Cotlect", 1, {"common": 1}), ("NEW!", 1, {"common": 1}), ("ouw", 1, {"legendary": 1}),
                       ("Fish", 2, {"rare": 2}), ("Lost Mask", 1, {"common": 1}), ("OuwFish", 3, {"common": 3})])
    changes = dict(Catalog(shared, local).tidy())
    assert changes == {"Jzebra Fish": "Zebra Fish", "Clovvn Fish": "Clown Fish", "Cotlect": None,
                       "NEW!": None, "ouw": None, "Fish": None}
    items = {i["name"]: i for i in _index(local)}
    assert set(items) == {"Zebra Fish", "Clown Fish", "Lost Mask", "OuwFish"}
    assert items["Zebra Fish"]["count"] == 8
    assert items["Zebra Fish"]["rarity_votes"] == {"rare": 7, "common": 1}
    assert "Jzebra Fish" in items["Zebra Fish"]["aliases"]
    assert items["Clown Fish"]["count"] == 5 and "Clovvn Fish" in items["Clown Fish"]["aliases"]
    # imagem do lixo e das leituras erradas não fica sobrando
    assert sorted(p.stem for p in (local / "imagens").glob("*.png")) == ["clown-fish", "lost-mask", "ouwfish", "zebra-fish"]
    assert Catalog(shared, local).tidy() == []  # arrumar de novo não muda nada


def test_arrumar_nunca_junta_o_maior_no_menor(dirs):
    """Dois itens só do local: a leitura errada (menos vezes) entra no nome certo (mais vezes)."""
    shared, local = dirs
    _old_local(local, [("Krathulon", 5, {"legendary": 5}), ("Krath LI lon", 1, {"legendary": 1})])
    assert dict(Catalog(shared, local).tidy()) == {"Krath LI lon": "Krathulon"}
    assert [i["name"] for i in _index(local)] == ["Krathulon"]


def test_arrumar_passa_a_imagem_para_o_nome_certo_se_ele_nao_tinha(dirs):
    shared, local = dirs
    _old_local(local, [("Krathulon", 5, {"legendary": 5}), ("Krath LI lon", 1, {"legendary": 1})])
    data = json.loads((local / "itens.json").read_text(encoding="utf-8"))
    data["items"][0]["image"] = None
    (local / "imagens" / "krathulon.png").unlink()
    (local / "itens.json").write_text(json.dumps(data), encoding="utf-8")
    Catalog(shared, local).tidy()
    item = _index(local)[0]
    assert item["image"] == "imagens/krathulon.png" and (local / item["image"]).exists()


def test_arrumar_no_empate_fica_o_nome_mais_completo(dirs):
    """Ensaio no catálogo real (24/09): "LOSt Cape" entrava em "ostCa e" (os dois com 1)."""
    shared, local = dirs
    _old_local(local, [("LOSt Cape", 1, {"mythic": 1}), ("ostCa e", 1, {"common": 1})])
    assert dict(Catalog(shared, local).tidy()) == {"ostCa e": "LOSt Cape"}


def test_arrumar_junta_pedaco_que_e_apelido_em_vez_de_apagar(known, dirs):
    """"Fwesh" é apelido conhecido de OuwFwesh: soma no item em vez de sumir como pedaço."""
    shared, local = dirs
    data = json.loads((shared / "itens.json").read_text(encoding="utf-8"))
    next(i for i in data["items"] if i["name"] == "OuwFwesh")["aliases"] = ["Fwesh"]
    (shared / "itens.json").write_text(json.dumps(data), encoding="utf-8")
    _old_local(local, [("Fwesh", 1, {"common": 1})])
    assert dict(Catalog(shared, local).tidy()) == {"Fwesh": "OuwFwesh"}


def test_arrumar_da_mais_uma_volta_depois_de_juntar(known, dirs):
    """"quebra Fish" empatava entre Zebra Fish e "Jzebra Fish" até o Jzebra ser juntado."""
    _, local = dirs
    _old_local(local, [("Jzebra Fish", 19, {"rare": 19}), ("quebra Fish", 1, {"rare": 1})])
    assert dict(Catalog(*dirs).tidy()) == {"Jzebra Fish": "Zebra Fish", "quebra Fish": "Zebra Fish"}


# ---------------------------------------------------------------- revisão de 24/09
def test_arrumar_nao_apaga_item_curto_de_verdade(dirs):
    """"Ore" com 40 pegos não é pedaço de "Refinement Ore": só apaga pedaço visto 1-2 vezes."""
    shared, local = dirs
    _old_local(local, [("Ore", 40, {"mythic": 40}), ("Refinement Ore", 17, {"rare": 17}), ("ouw", 1, {})])
    changes = dict(Catalog(shared, local).tidy())
    assert "Ore" not in changes
    assert {i["name"] for i in _index(local)} == {"Ore", "Refinement Ore", "ouw"}  # ouw: nada conhecido com ele


def test_arrumar_nao_junta_itens_parecidos_vistos_muitas_vezes(dirs):
    """Anglerfish x Angelfish (0,842): 12 pegos não é leitura errada, é outro peixe."""
    shared, local = dirs
    _old_local(local, [("Angelfish", 50, {"rare": 50}), ("Anglerfish", 12, {"rare": 12})])
    assert Catalog(shared, local).tidy() == []


def test_leitura_rara_parecida_junta(dirs):
    shared, local = dirs
    _old_local(local, [("Krathulon", 72, {"legendary": 72}), ("KrathLtlon", 3, {"legendary": 3})])
    assert dict(Catalog(shared, local).tidy()) == {"KrathLtlon": "Krathulon"}


def test_arrumar_guarda_copia_antes_de_mudar(dirs):
    shared, local = dirs
    _old_local(local, [("Coral", 5, {"common": 5}), ("NEW!", 1, {})])
    before = (local / "itens.json").read_text(encoding="utf-8")
    Catalog(shared, local).tidy()
    assert (local / "itens.antes-de-arrumar.json").read_text(encoding="utf-8") == before


def test_chute_por_semelhanca_nao_vira_apelido_gravado(dirs):
    """Nome novo parecido (0,84) usa o conhecido na hora, mas não fica gravado como apelido:
    senão um item novo de verdade ficaria preso ao nome errado (e iria para os amigos)."""
    cat = Catalog(*dirs)
    cat.record("Angelfish", "rare", IMG)
    assert cat.record("Anglerfish", "rare", IMG).name == "Angelfish"
    assert _index(dirs[1])[0]["aliases"] == []


def test_collector_nao_e_o_botao_collect():
    import catalog
    assert catalog.plausible_name("Collector") and catalog.plausible_name("Collected")


# ---------------------------------------------------------------- a ficha do catálogo manda (24/09)
def _shared_card(shared, name, rarity, with_image=True):
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "imagens").mkdir(exist_ok=True)
    slug = name.lower().replace(" ", "-")
    image = None
    if with_image:
        card = np.full((30, 90, 3), 77, np.uint8)
        import cv2
        cv2.imwrite(str(shared / "imagens" / f"{slug}.png"), card)
        image = f"imagens/{slug}.png"
    item = {"name": name, "slug": slug, "image": image, "rarity": rarity, "rarity_votes": {}, "aliases": []}
    (shared / "itens.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")


def test_raridade_da_ficha_do_catalogo_manda(dirs):
    """Pedido de 24/09: a raridade vem da ficha do item, não da cor lida na tela."""
    shared, local = dirs
    _shared_card(shared, "Lost Cape", "mythic")
    cat = Catalog(shared, local)
    for _ in range(10):
        rec = cat.record("Lost Cape", "common", IMG)
    assert rec.rarity == "mythic"
    assert cat.record("LO$t Cape", "rare", IMG).rarity == "mythic"


def test_ficha_com_raridade_invalida_usa_as_leituras(dirs):
    shared, local = dirs
    _shared_card(shared, "Coral", "roxo")
    cat = Catalog(shared, local)
    cat.record("Coral", "common", IMG)
    assert cat.record("Coral", "common", IMG).rarity == "common"


def test_publicar_nao_troca_a_raridade_que_esta_na_ficha(dirs):
    """Quem corrigir a raridade à mão no itens.json não pode perder a correção no publicar."""
    shared, local = dirs
    _shared_card(shared, "Lost Mask", "mythic")
    cat = Catalog(shared, local)
    for _ in range(5):
        cat.record("Lost Mask", "common", IMG)
    cat.publish()
    assert _index(shared)[0]["rarity"] == "mythic"


def test_imagem_da_ficha_vai_para_o_aviso(dirs):
    shared, local = dirs
    _shared_card(shared, "Lost Cape", "mythic")
    cat = Catalog(shared, local)
    card = cat.card_image("LO$t Cape")
    assert card is not None and card.shape == (30, 90, 3) and int(card[0, 0, 0]) == 77
    assert cat.card_image("Item Desconhecido") is None


def test_sem_imagem_no_compartilhado_usa_a_do_local(dirs):
    shared, local = dirs
    _shared_card(shared, "Coral", "common", with_image=False)
    cat = Catalog(shared, local)
    cat.record("Coral", "common", np.full((20, 60, 3), 5, np.uint8))
    card = cat.card_image("Coral")
    assert card is not None and int(card[0, 0, 0]) == 5



def test_catalogo_do_repositorio_reconhece_o_ore_lido_torto():
    """O Ore (mythic) lido "v?Ore"/"ROre" vira Ore; Refinement Ore continua outro item."""
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent / "catalogo"
    cat = Catalog(repo, repo.with_name("sem_local_no_teste"))
    assert cat.resolve("v?Ore") == "Ore" and cat.resolve("ROre") == "Ore"
    assert cat.resolve("Refinement Ore") == "Refinement Ore"


def test_preco_vem_da_ficha(dirs):
    shared, local = dirs
    shared.mkdir(parents=True)
    items = [{"name": "Zebra Fish", "slug": "zebra-fish", "image": None, "rarity": "rare", "rarity_votes": {},
              "aliases": [], "price": 66},
             {"name": "Coral", "slug": "coral", "image": None, "rarity": "common", "rarity_votes": {},
              "aliases": [], "price": "muito"},
             {"name": "Ore", "slug": "ore", "image": None, "rarity": "mythic", "rarity_votes": {},
              "aliases": [], "price": -5}]
    (shared / "itens.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    assert Catalog(shared, local).prices() == {"Zebra Fish": 66}  # preço inválido é ignorado
