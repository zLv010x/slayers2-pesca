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
    "auto_camera": True,  # tenta girar a câmera sozinha antes de pausar esperando a pessoa
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
        "collect_hold_sec": 3.25,
        "collect_timeout_sec": 12.0,
        "ground_pickup_sec": 12.0,
        "popup_wait_sec": 3.0,
        "after_collect_sec": 0.5,
        "rod_equip_wait_sec": 0.8,
        "recovery_wait_sec": 30.0,
        "refocus_after_sec": 15.0,
        # numa pausa longa (câmera, ponto fora da tela, recuperação) com o Roblox na frente,
        # mexe o mouse 1px a cada tanto para o jogo não desconectar por 20 min sem input. 0 desliga.
        "anti_idle_sec": 240.0,
    },
    "limits": {
        "rod_retries": 3,
        "max_failed_casts": 5,
        "max_recoveries": 10,
        # pesca rodando a noite toda sem ninguém olhando: se parar sozinha (não
        # foi F1/botão/fechar), tenta de novo depois disso. 0 desliga.
        "auto_restart_wait_min": 5,
        "max_restarts_per_hour": 3,
    },
    "tracking": {
        "task_fps": 30.0,
        "accel_hold": 900.0,
        "accel_release": 900.0,
        "ball_ref_px": 24.0,
        "latency_s": 0.10,
        "hysteresis_px": 6.0,
        "aim_offset": 0.0,
        "zone_hold_s": 1.0,
    },
    "baits": {
        "enabled": True,
        # ordem de preferência: a primeira que tiver é a usada
        "order": ["Fish Head", "Drowned Lure", "Worm"],
        "infinite": ["Drowned Lure"],   # iscas que não gastam
        "recheck_at": 10,               # confere o inventário quando faltarem isso
    },
    # overlay_pos: {"x", "y"} em fração da janela do Roblox (None = em cima da party)
    # Auto relog: quando o jogo cai (menu/Disconnected), reconecta sozinho. Só funciona com o
    # gamepass de spawn e o spawn setado no ponto de pesca (senão nasce longe da água).
    "relog": {
        "enabled": False,
        "has_spawn_gamepass": False,
        "spawn_set": False,
        "server_mode": "vip",          # "vip" = servidor privado próprio | "nick" = de outra pessoa
        "owner_nick": "",
        "map_name": "Ouwland",
        "hold_join_sec": 3.0,
        "step_timeout_sec": 90.0,
        "total_timeout_sec": 600.0,
        "settle_sec": 8.0,
        "max_per_hour": 4,
        "no_reconnect_codes": [264],   # 264 = a conta entrou de outro PC: reconectar derrubaria
    },
    "ui": {"always_on_top": True, "show_recent": True, "minimize_on_start": True,
           "overlay": True, "overlay_pos": None,
           "show_in_capture": False},  # aparecer no Parsec/OBS (a macro se apaga dos próprios prints)
    "config_rev": 3,
}
CONFIG_REV = DEFAULTS["config_rev"]
OLD_START_TIMEOUT = 20.0  # padrão da versão 1 do config
OLD_GROUND_PICKUP_SEC = 8.0  # padrão da versão 2 do config (só dava 1 tentativa)


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
    if rev < 3 and cfg["timings"]["ground_pickup_sec"] == OLD_GROUND_PICKUP_SEC:
        cfg["timings"]["ground_pickup_sec"] = DEFAULTS["timings"]["ground_pickup_sec"]
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
