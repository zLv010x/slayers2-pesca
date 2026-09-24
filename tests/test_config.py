import copy
import json

import config


def test_ground_pickup_sec_padrao_agora_e_12s():
    # log real: com 8s só dava 1 tentativa de pegar do chão; 12s cabem mais tentativas
    assert config.DEFAULTS["timings"]["ground_pickup_sec"] == 12.0


def test_migra_configuracao_antiga_que_nunca_mudou_o_padrao_de_8s(tmp_path):
    path = tmp_path / "config.json"
    old = copy.deepcopy(config.DEFAULTS)
    old["timings"]["ground_pickup_sec"] = 8.0  # padrão antigo, nunca mudado pela pessoa
    old["config_rev"] = 2
    path.write_text(json.dumps(old), encoding="utf-8")
    cfg = config.load(path)
    assert cfg["timings"]["ground_pickup_sec"] == 12.0
    assert cfg["config_rev"] == config.CONFIG_REV


def test_preserva_valor_customizado_mesmo_com_revisao_antiga(tmp_path):
    path = tmp_path / "config.json"
    old = copy.deepcopy(config.DEFAULTS)
    old["timings"]["ground_pickup_sec"] = 5.0  # a pessoa mudou de propósito
    old["config_rev"] = 2
    path.write_text(json.dumps(old), encoding="utf-8")
    cfg = config.load(path)
    assert cfg["timings"]["ground_pickup_sec"] == 5.0


def test_nao_mexe_de_novo_se_ja_esta_na_revisao_atual(tmp_path):
    path = tmp_path / "config.json"
    cfg_atual = copy.deepcopy(config.DEFAULTS)
    cfg_atual["timings"]["ground_pickup_sec"] = 8.0  # escolha da pessoa, já na revisão atual
    cfg_atual["config_rev"] = config.CONFIG_REV
    path.write_text(json.dumps(cfg_atual), encoding="utf-8")
    cfg = config.load(path)
    assert cfg["timings"]["ground_pickup_sec"] == 8.0
