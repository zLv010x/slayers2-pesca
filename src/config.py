"""Configuração salva em config.json (tudo editável pela interface)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
CALIBRATION_DIR = ROOT / "calibracao"
LOG_DIR = ROOT / "logs"
CATALOG_DIR = ROOT / "catalogo"              # compartilhado (vai para o GitHub)
CATALOG_LOCAL_DIR = ROOT / "catalogo_local"  # só deste PC

# Área do painel da party (canto esquerdo): nunca clicar ali.
PARTY_ZONE = {"x0": 0.0, "x1": 0.14, "y0": 0.40, "y1": 0.60}

DEFAULTS: dict = {
    "hotkeys": {"start_stop": "F1", "set_cast_point": "F2", "exit": "F3"},
    "rod_key": "3",
    "cast_point": None,  # {"x": 0.47, "y": 0.39} em fração da área do jogo
    "scan_area": {"x": 0.731640625, "y": 0.2923611111111111, "w": 0.03828125, "h": 0.3763888888888889},
    "compass_lock": True,
    "compass_tolerance_px": 6,
    "ground_pickup": True,
    "discord": {
        "webhook_url": "",
        "user_id": "",
        "ping_rarities": ["mythic"],
        "send_image": True,
        "tracked_item": "Ore",
        "notify_problems": True,
    },
    "timings": {
        "after_cast_sec": 0.3,
        "minigame_start_timeout_sec": 10.0,
        "minigame_max_sec": 120.0,
        "ball_lost_sec": 1.5,
        "after_minigame_sec": 1.0,
        "collect_hold_sec": 3.0,
        "collect_timeout_sec": 12.0,
        "ground_pickup_sec": 8.0,
        "popup_wait_sec": 3.0,
        "after_collect_sec": 0.5,
        "rod_equip_wait_sec": 0.8,
        "recovery_wait_sec": 30.0,
        "refocus_after_sec": 15.0,
    },
    "limits": {
        "rod_retries": 3,
        "max_failed_casts": 5,
        "max_recoveries": 10,
    },
    "tracking": {
        "task_fps": 30.0,
        "lead_s": 0.02,          # atraso extra previsto (além do tempo entre leituras)
        "deadband": 0.05,        # zona morta em volta do meio da zona verde (fração)
        "accel": 37.5,           # aceleração do quadrado (alturas do quadrado por s²)
        "zone_memory_s": 1.0,    # usa a última zona vista por esse tempo
    },
    "baits": {
        "enabled": True,
        # ordem de preferência: a primeira que tiver é a usada
        "order": ["Fish Head", "Drowned Lure", "Worm"],
        "infinite": ["Drowned Lure"],   # iscas que não gastam
        "recheck_at": 10,               # confere o inventário quando faltarem isso
    },
    "ui": {"always_on_top": True, "show_recent": True, "minimize_on_start": True},
    "config_rev": 2,
}
CONFIG_REV = DEFAULTS["config_rev"]
OLD_START_TIMEOUT = 20.0  # padrão da versão 1 do config


def _merge(base: dict, data: dict) -> dict:
    """Copia de base com os valores de data que tiverem o mesmo tipo."""
    out = copy.deepcopy(base)
    for key, default in base.items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(default, dict) and isinstance(value, dict):
            out[key] = _merge(default, value)
        elif default is None or isinstance(value, type(default)) or (
            isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool)
        ):
            out[key] = float(value) if isinstance(default, float) else value
    return out


def load(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.replace(path.with_suffix(".json.bak"))
        return copy.deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULTS)
    rev = data.get("config_rev", 1)
    return _migrate(_merge(DEFAULTS, data), rev if isinstance(rev, int) else 1)


def _migrate(cfg: dict, rev: int) -> dict:
    """Atualiza padrões antigos que a pessoa nunca mudou."""
    if rev < 2 and cfg["timings"]["minigame_start_timeout_sec"] == OLD_START_TIMEOUT:
        cfg["timings"]["minigame_start_timeout_sec"] = DEFAULTS["timings"]["minigame_start_timeout_sec"]
    cfg["config_rev"] = CONFIG_REV
    return cfg


def save(cfg: dict, path: Path = CONFIG_PATH) -> None:
    """Grava num arquivo temporário e troca: um travamento nunca corrompe o config."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def in_party_zone(x: float, y: float) -> bool:
    z = PARTY_ZONE
    return z["x0"] <= x <= z["x1"] and z["y0"] <= y <= z["y1"]
