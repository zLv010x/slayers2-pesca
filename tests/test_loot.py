import pytest
import numpy as np

from loot import _parse_qty, classify_rarity, item_snapshot, read_popup


def test_le_nome_quantidade_e_raridade_do_aviso(shot):
    loot = read_popup(shot("popup_golden_fish.webp"))
    assert loot is not None
    assert loot.name == "Golden Fish"
    assert loot.quantity == 1
    assert loot.rarity == "rare"


def test_prompt_de_coleta_nao_conta_como_item_pego(shot):
    # "Golden Fish / Collect" aparece ANTES de segurar T: não é um drop ainda.
    assert read_popup(shot("prompt_golden_fish.webp")) is None


def test_sem_aviso_na_tela(shot):
    assert read_popup(shot("idle_com_vara.webp")) is None


def test_recorte_do_item_para_o_discord(shot):
    frame = shot("popup_golden_fish.webp")
    snap = item_snapshot(frame, read_popup(frame))
    assert snap.shape[0] > 20 and snap.shape[1] > 90


def test_quantidade_tolera_erros_do_ocr():
    assert _parse_qty("x1") == 1
    assert _parse_qty("- xl") == 1
    assert _parse_qty("x17") == 17
    assert _parse_qty("Golden Fish") is None


def _band(bgr):
    return np.full((10, 60, 3), bgr, np.uint8)


def test_cores_de_raridade():
    assert classify_rarity(_band((200, 120, 40))) == "rare"       # azul
    assert classify_rarity(_band((30, 180, 230))) == "legendary"  # dourado
    assert classify_rarity(_band((30, 30, 220))) == "mythic"      # vermelho
    assert classify_rarity(_band((200, 60, 150))) == "epic"       # roxo
    assert classify_rarity(_band((90, 90, 90))) == "common"       # cinza


def test_cores_reais_do_inventario(shot):
    inv = shot("inventario_raridades.webp")
    # Fundo de um item de cada linha do inventário (canto inferior esquerdo do quadrado).
    def fundo(col, row):
        x, y = 30 + 103 * col + 4, 88 + 104 * row + 70
        return inv[y:y + 12, x:x + 14]
    assert classify_rarity(fundo(0, 0)) == "rare"
    assert classify_rarity(fundo(0, 2)) == "epic"
    assert classify_rarity(fundo(0, 4)) == "legendary"
    assert classify_rarity(fundo(0, 6)) == "mythic"


def test_so_conta_avisos_novos():
    from loot import Loot, new_items
    box = (0, 0, 1, 1)
    antes = [Loot("Metal Scraps", 5, "common", box), Loot("Golden Fish", 1, "rare", box)]
    depois = antes + [Loot("Metal Scraps", 5, "common", box), Loot("Ore", 1, "common", box)]
    novos = new_items(antes, depois)
    assert [(i.name, i.quantity) for i in novos] == [("Metal Scraps", 5), ("Ore", 1)]


def test_selo_new_conta_como_um_e_marca_item_novo(shot):
    import cv2
    frame = shot("popup_golden_fish.webp").copy()
    x, y, w, h = read_popup(frame).box
    # Troca o "x1" pelo selo amarelo "NEW!" (como o jogo faz com item inédito).
    cv2.rectangle(frame, (x + 12, y + h + 3), (x + w - 12, y + 2 * h + 5), (20, 200, 250), -1)
    cv2.putText(frame, "NEW!", (x + 30, y + 2 * h + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (20, 20, 20), 1)
    loot = read_popup(frame)
    assert loot is not None
    assert (loot.name, loot.quantity, loot.is_new) == ("Golden Fish", 1, True)
    assert loot.rarity == "rare"  # o amarelo do selo não pode virar "legendary"


def test_nome_curto_com_quantidade_ao_lado_coral(shot):
    # Bug real: com nome curto o "x1" fica centralizado na faixa, à direita do texto.
    loot = read_popup(shot("popup_coral.webp"))
    assert loot is not None
    assert (loot.name, loot.quantity) == ("Coral", 1)


def test_limpa_sujeira_do_ocr_no_nome():
    from loot import clean_name
    assert clean_name("'Zebra Fish") == "Zebra Fish"
    assert clean_name("- Coral .") == "Coral"
    assert clean_name("Black Dragon Armour") == "Black Dragon Armour"
    assert clean_name("!!") == ""


def test_letra_solta_antes_do_nome_sai():
    from loot import clean_name
    assert clean_name("U Zebra Fish") == "Zebra Fish"
    assert clean_name("H Zebra Fish") == "Zebra Fish"
    assert clean_name("Zebra Fish") == "Zebra Fish"
    assert clean_name("Ore") == "Ore"


def test_coral_e_comum_nao_legendary(shot):
    # o brilho bege atrás do nome + madeira marrom viravam "dourado"
    assert read_popup(shot("popup_coral.webp")).rarity == "common"


@pytest.mark.parametrize("name, title_bar, expected", [
    ("popup_coral.webp", 0, "Coral"),
    ("popup_golden_fish.webp", 18, "Golden Fish"),
])
def test_le_o_aviso_em_tela_1920(shot, name, title_bar, expected):
    import cv2
    img = shot(name)[title_bar:]
    scale = 1920 / img.shape[1]
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    loot = read_popup(small)
    assert loot is not None and (loot.name, loot.quantity) == (expected, 1)


def test_aviso_pequeno_em_janela_1002(shot):
    # print real do Inside (Roblox em janela 1002x981): nome com ~9 px e aviso apagando
    loot = read_popup(shot("popup_janela_1002.webp"))
    assert loot is not None and (loot.name, loot.quantity) == ("Zebra Fish", 1)


# --- raridade pelas bordas coloridas da faixa ------------------------------------
# Recortes reais do catálogo (item_snapshot da 1ª vez que o item apareceu). O recorte vai de
# 3h à esquerda até h à direita do nome e de h acima até 3h abaixo, então a caixa do OCR
# gravada é (3h, h, w, h) com h = altura/4. Todos eram lidos errado pelo método antigo.

def _caixa_do_recorte(img):
    h = img.shape[0] // 4
    return 3 * h, h, img.shape[1] - 4 * h, h


def _raridade_do_recorte(shot, name):
    import loot
    img = shot(name)
    box = _caixa_do_recorte(img)
    return loot.popup_rarity(img, box, is_new=loot.has_new_badge(img, *box))


@pytest.mark.parametrize("name, expected", [
    # madeira do píer (H 10-13, S ~110) atrás da faixa contava como "dourado"
    ("aviso_rare_madeira_zebra_fish.png", "rare"),
    ("aviso_rare_madeira_refinement_ore.png", "rare"),
    ("aviso_common_madeira_ouwfish.png", "common"),
    # caixa do OCR com o ícone dourado junto ("v?Ore") e deslocada 12 px do nome
    ("aviso_mythic_ore_caixa_com_icone.png", "mythic"),
    # Lost Cape com selo NEW! à noite: faixa vermelha escura, caixa 19 px acima do nome
    ("aviso_mythic_lost_cape_new_noite.png", "mythic"),
    # aviso ainda surgindo (meio transparente): a média da faixa não chega a 15% de cor
    ("aviso_rare_apagando_noite_clown_fish.png", "rare"),
    ("aviso_rare_apagando_pedra_clown_fish.png", "rare"),
])
def test_raridade_certa_nos_avisos_que_eram_lidos_errado(shot, name, expected):
    assert _raridade_do_recorte(shot, name) == expected


@pytest.mark.parametrize("name, expected", [
    ("aviso_legendary_krathulon.png", "legendary"),
    ("aviso_mythic_lost_cape.png", "mythic"),
    ("aviso_common_noite_metal_scraps.png", "common"),
    ("aviso_common_pedra_sea_horse.png", "common"),
])
def test_raridade_que_ja_era_certa_continua_certa(shot, name, expected):
    assert _raridade_do_recorte(shot, name) == expected


@pytest.mark.parametrize("dy", [-4, 0, 4])
def test_raridade_aguenta_caixa_do_ocr_um_pouco_deslocada(shot, dy):
    import loot
    frame = shot("popup_golden_fish.webp")
    x, y, w, h = read_popup(frame).box
    assert loot.popup_rarity(frame, (x, y + dy, w, h)) == "rare"


def _fundo_com_nome(fundo_bgr):
    img = np.full((120, 300, 3), fundo_bgr, np.uint8)
    img[50:62, 60:240] = 235  # "nome" branco
    return img, (60, 50, 180, 12)


@pytest.mark.parametrize("fundo", [
    (140, 90, 30),   # água/céu azul (fazia o Ewerton ler "rare" em item comum)
    (35, 47, 63),    # madeira do píer (virava "legendary")
    (30, 30, 160),   # vermelho liso
])
def test_fundo_liso_colorido_nao_e_raridade(fundo):
    import loot
    img, box = _fundo_com_nome(fundo)
    assert loot.popup_rarity(img, box) == "common"


def _linha_tracejada(img, y, x0, x1, bgr, cheio=0.55):
    """Linha de 2 px que cobre só 'cheio' de cada trecho (borda fraca/apagando)."""
    passo = 10
    for x in range(x0, x1, passo):
        img[y:y + 2, x:x + int(passo * cheio)] = bgr


def test_duas_bordas_fracas_em_volta_do_nome_dao_a_cor():
    import loot
    img, (x, y, w, h) = _fundo_com_nome((90, 90, 90))
    _linha_tracejada(img, y - 8, x, x + w, (200, 120, 40))
    _linha_tracejada(img, y + h + 9, x, x + w, (200, 120, 40))
    assert loot.popup_rarity(img, (x, y, w, h)) == "rare"


def test_um_risco_fraco_solto_no_fundo_nao_da_cor():
    # borda fraca sozinha (sem a de baixo) é mais provável ser um risco do cenário
    import loot
    img, (x, y, w, h) = _fundo_com_nome((90, 90, 90))
    _linha_tracejada(img, y - 8, x, x + w, (200, 120, 40))
    assert loot.popup_rarity(img, (x, y, w, h)) == "common"


def test_selo_new_amarelo_nao_vira_legendary_em_item_comum(shot):
    import cv2
    import loot
    frame = shot("popup_coral.webp").copy()
    x, y, w, h = read_popup(frame).box
    cv2.rectangle(frame, (x, y + h + 3), (x + w, y + 2 * h + 5), (20, 200, 250), -1)
    assert loot.has_new_badge(frame, x, y, w, h)
    assert loot.popup_rarity(frame, (x, y, w, h), is_new=True) == "common"


def test_nome_sem_letras_suficientes_e_lixo():
    # 24/09 02:28: no menu principal, o "6d" do painel de códigos virou um "item"
    import loot
    assert not loot.plausible_name("6d")
    assert not loot.plausible_name("x2")
    assert not loot.plausible_name("Collect")
    assert not loot.plausible_name("item")
    assert loot.plausible_name("Ore")
    assert loot.plausible_name("Zebra Fish")
    assert loot.plausible_name("OuwFish")


# --- nomes que não existem (25/09) ---------------------------------------------------
# Recortes reais do catálogo local do usuário (item_snapshot de leituras erradas) postos de volta
# num quadro do tamanho da tela, no lugar onde o aviso aparece.

def _no_quadro(recorte, largura=1920, altura=1080):
    borda = np.concatenate([recorte[0], recorte[-1], recorte[:, 0], recorte[:, -1]])
    quadro = np.empty((altura, largura, 3), np.uint8)
    quadro[:] = np.median(borda, axis=0).astype(np.uint8)
    x0, y0 = int(0.55 * largura), int(0.45 * altura)
    quadro[y0:y0 + recorte.shape[0], x0:x0 + recorte.shape[1]] = recorte
    return quadro


@pytest.fixture
def conhecido():
    """Reconhecedor com o catálogo compartilhado do repositório (só leitura)."""
    from pathlib import Path

    from catalog import Catalog
    repo = Path(__file__).resolve().parent.parent / "catalogo"
    return Catalog(repo, repo.with_name("sem_local_no_teste")).knows


@pytest.mark.parametrize("recorte", ["aviso_lido_errado_crustadon_1.png", "aviso_lido_errado_crustadon_2.png"])
def test_prefere_a_leitura_que_o_catalogo_reconhece(shot, conhecido, recorte):
    # 24-25/09: a variante com mais letras ("C r LI Stad o II", "rufitaclon") ganhava de outra
    # variante que tinha lido "Crustadon" certinho
    import loot
    quadro = _no_quadro(shot(recorte))
    nomes = [i.name for i in loot.read_popups(quadro, known=conhecido)]
    assert len(nomes) == 1 and conhecido(nomes[0]), nomes


def test_sem_reconhecedor_escolhe_como_antes(monkeypatch):
    import loot
    por_variante = {
        (200, 2): [loot.Loot("J V uaJZebra Fish", 1, "rare", (0, 0, 10, 10))],
        (155, 3): [loot.Loot("Zebra Fish", 1, "rare", (0, 0, 10, 10))],
    }
    monkeypatch.setattr(loot, "_read_popups_once", lambda frame, thr, up, known=None: por_variante[(thr, up)])
    variantes = tuple(por_variante)
    assert loot.read_popups(None, variants=variantes)[0].name == "J V uaJZebra Fish"
    escolhido = loot.read_popups(None, variants=variantes, known=lambda n: n == "Zebra Fish")
    assert escolhido[0].name == "Zebra Fish"


def test_marca_nome_lido_por_uma_variante_so(monkeypatch):
    import loot
    caixa = (0, 0, 10, 10)
    por_variante = {
        (200, 2): [loot.Loot("Shotgun Schematic", 1, "legendary", caixa), loot.Loot("Clovurn Fish", 1, "rare", caixa)],
        (155, 3): [loot.Loot("Shotgun Schematic", 1, "legendary", caixa), loot.Loot("Clown Fish", 1, "rare", caixa)],
        (None, 3): [],
    }
    monkeypatch.setattr(loot, "_read_popups_once", lambda frame, thr, up, known=None: por_variante[(thr, up)])
    itens = loot.read_popups(None, variants=tuple(por_variante))
    assert [(i.name, i.lone) for i in itens] == [("Shotgun Schematic", False), ("Clovurn Fish", True)]
    # uma variante só rodando (checagem rápida): não dá para comparar, não marca
    rapido = loot.read_popups(None, variants=((200, 2),), best=False)
    assert not any(i.lone for i in rapido)


def test_nome_partido_em_duas_linhas_vira_um_aviso_so(monkeypatch):
    # 24/09 22:44 (usuário) e 25/09 00:11 (Ewerton): "Fish" e "Zebra" do mesmo aviso viravam dois
    # itens, cada um com o mesmo "x1"
    import loot
    from ocr import Line
    linhas = [Line("Fish", 1255, 600, 40, 20), Line("Zebra", 1200, 603, 50, 20), Line("x1", 1240, 628, 16, 12)]
    monkeypatch.setattr(loot.ocr, "read_lines", lambda img, min_height=0: [
        Line(l.text, l.x - 940, l.y - 270, l.w, l.h) for l in linhas])
    monkeypatch.setattr(loot, "popup_rarity", lambda *a, **kw: "rare")
    quadro = np.zeros((1080, 1920, 3), np.uint8)
    itens = loot._read_popups_once(quadro, 200, 2)
    assert [(i.name, i.quantity) for i in itens] == [("Zebra Fish", 1)]
    assert itens[0].box == (1200, 600, 95, 23)


def test_nao_junta_nome_reconhecido_com_texto_ao_lado(monkeypatch):
    import loot
    from ocr import Line
    linhas = [Line("Zebra Fish", 1200, 600, 95, 20), Line("Olá", 1310, 600, 30, 20), Line("x1", 1240, 628, 16, 12)]
    monkeypatch.setattr(loot.ocr, "read_lines", lambda img, min_height=0: [
        Line(l.text, l.x - 940, l.y - 270, l.w, l.h) for l in linhas])
    monkeypatch.setattr(loot, "popup_rarity", lambda *a, **kw: "rare")
    quadro = np.zeros((1080, 1920, 3), np.uint8)
    itens = loot._read_popups_once(quadro, 200, 2, known=lambda n: n == "Zebra Fish")
    assert "Zebra Fish" in [i.name for i in itens]


def test_limpeza_do_nome_nao_corta_letras_de_leitura_cortada():
    # "uwFvvesh" = OuwFwesh sem o "O": quem decide se o começo é sujeira é o catálogo
    from loot import clean_name
    assert clean_name("uwFvvesh") == "uwFvvesh"
    assert clean_name("zMythic Refinement Ore") == "zMythic Refinement Ore"


def test_pedaco_do_botao_collect_nao_vira_aviso(shot):
    # 25/09: "xg•.ollec" = "Golde(n Fish) / Collect" do item no chão, com o "x1" de outro aviso perto
    import loot
    assert loot.read_popups(_no_quadro(shot("aviso_botao_collect_golden.png"))) == []


def test_item_novo_de_verdade_continua_sendo_lido(shot, conhecido):
    import loot
    itens = loot.read_popups(_no_quadro(shot("aviso_item_novo_shotgun_schematic.png")), known=conhecido)
    assert [(i.name, i.lone) for i in itens] == [("Shotgun Schematic", False)]
