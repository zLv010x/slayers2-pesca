"""i18n: `_()` em pt/en, texto sem tradução e a pílula de status nos dois idiomas."""
from types import SimpleNamespace

import pytest

import app
import i18n


@pytest.fixture(autouse=True)
def _volta_para_pt():
    """O idioma é global (fixado uma vez, ao abrir a macro): garante que um teste não
    vaze o idioma "en" para os outros arquivos de teste."""
    yield
    i18n.set_language("pt")


def test_em_portugues_devolve_o_texto_igual():
    i18n.set_language("pt")
    assert i18n._("Pausado") == "Pausado"
    assert i18n._("Pausado: {msg}.", msg="teste") == "Pausado: teste."


def test_em_ingles_devolve_a_traducao():
    i18n.set_language("en")
    assert i18n._("Pausado") == "Paused"
    assert i18n._("Pausado: {msg}.", msg="test") == "Paused: test."


def test_texto_sem_traducao_cai_no_portugues():
    i18n.set_language("en")
    texto = "Isto não está no dicionário EN de propósito."
    assert i18n._(texto) == texto


def test_idioma_invalido_vira_pt():
    i18n.set_language("fr")
    assert i18n.get_language() == "pt"
    assert i18n._("Pausado") == "Pausado"


def _fake_app(**over):
    calls = {"status": [], "pill": []}
    fake = SimpleNamespace(
        _running=True,
        status=SimpleNamespace(configure=lambda **kw: calls["status"].append(kw)),
        pill=SimpleNamespace(configure=lambda **kw: calls["pill"].append(kw)),
    )
    for key, value in over.items():
        setattr(fake, key, value)
    return fake, calls


def test_pilula_fica_amarela_em_pausado_pt():
    i18n.set_language("pt")
    fake, calls = _fake_app()
    app.App.set_status(fake, "Pausado: o Roblox não está na frente.")
    assert calls["pill"][-1]["fg_color"] == app.AMBER
    assert calls["pill"][-1]["text"] == "Pausado"


def test_pilula_fica_amarela_em_paused_en():
    i18n.set_language("en")
    fake, calls = _fake_app()
    app.App.set_status(fake, "Paused: Roblox isn't in the foreground.")
    assert calls["pill"][-1]["fg_color"] == app.AMBER
    assert calls["pill"][-1]["text"] == "Paused"


def test_pilula_fica_amarela_em_recuperando_pt():
    i18n.set_language("pt")
    fake, calls = _fake_app()
    app.App.set_status(fake, "Recuperando (1/10): algo deu errado.")
    assert calls["pill"][-1]["fg_color"] == app.AMBER
    assert calls["pill"][-1]["text"] == "Recuperando"


def test_pilula_fica_amarela_em_recovering_en():
    i18n.set_language("en")
    fake, calls = _fake_app()
    app.App.set_status(fake, "Recovering (1/10): something went wrong.")
    assert calls["pill"][-1]["fg_color"] == app.AMBER
    assert calls["pill"][-1]["text"] == "Recovering"


@pytest.mark.parametrize("lang, texto", [("pt", "Lançando..."), ("en", "Casting...")])
def test_pilula_fica_verde_fora_de_pausa_ou_recuperacao(lang, texto):
    i18n.set_language(lang)
    fake, calls = _fake_app()
    app.App.set_status(fake, texto)
    assert calls["pill"][-1]["fg_color"] == app.GREEN


def test_pilula_nao_muda_quando_nao_esta_pescando():
    fake, calls = _fake_app(_running=False)
    app.App.set_status(fake, "Pausado: qualquer coisa.")
    assert calls["status"] == [{"text": "Pausado: qualquer coisa."}]
    assert calls["pill"] == []



def test_raridade_comum_em_ingles():
    import i18n
    import webhook
    i18n.set_language("en")
    try:
        assert webhook.rarity_label("common") == "Common" and webhook.rarity_label("mythic") == "Mythic"
    finally:
        i18n.set_language("pt")
    assert webhook.rarity_label("common") == "Comum"
