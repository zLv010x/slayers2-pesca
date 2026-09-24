"""Aba Relog: a linha de estado diz o que falta, na ordem em que a pessoa precisa resolver."""
import pytest

import config
import relog_tab


def _cfg(**over):
    cfg = {"relog": dict(config.DEFAULTS["relog"])}
    cfg["relog"].update(over)
    return cfg


READY = dict(enabled=True, has_spawn_gamepass=True, spawn_set=True, server_mode="vip")


def test_desligado_e_neutro():
    text, tone = relog_tab.status_line(_cfg())
    assert tone == "off" and "desligado" in text.lower()


def test_sem_gamepass_nao_reconecta():
    text, tone = relog_tab.status_line(_cfg(**dict(READY, has_spawn_gamepass=False)))
    assert tone == "bad" and "gamepass" in text.lower()


def test_servidor_de_outro_sem_nick_avisa_o_nick_mesmo_sem_spawn():
    """O nick falta de verdade; o spawn a macro seta sozinha. Avisar o que a pessoa precisa fazer."""
    text, tone = relog_tab.status_line(_cfg(**dict(READY, spawn_set=False, server_mode="nick")))
    assert tone == "bad" and "nick" in text.lower()


def test_falta_setar_o_spawn_e_aviso_amarelo():
    text, tone = relog_tab.status_line(_cfg(**dict(READY, spawn_set=False)))
    assert tone == "warn" and "spawn" in text.lower()


@pytest.mark.parametrize("over", [{}, {"server_mode": "nick", "owner_nick": "Lv_010"}])
def test_pronto(over):
    text, tone = relog_tab.status_line(_cfg(**dict(READY, **over)))
    assert tone == "ok" and "pronto" in text.lower()


def test_nick_so_de_espacos_conta_como_vazio():
    _, tone = relog_tab.status_line(_cfg(**dict(READY, server_mode="nick", owner_nick="   ")))
    assert tone == "bad"
