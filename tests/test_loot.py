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
