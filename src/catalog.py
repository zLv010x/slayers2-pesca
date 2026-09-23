"""Catálogo de itens: uma imagem por item e um índice (catalogo/itens.json).

Serve para a macro reconhecer melhor os itens:
- corrige erros do OCR comparando com os nomes já conhecidos ("Corai" -> "Coral");
- usa a raridade mais vista daquele item em vez de confiar só na cor da vez;
- avisa quando um item aparece pela primeira vez.

Dá para editar o itens.json à mão (ex.: corrigir um nome): o que estiver em
"aliases" passa a ser lido como o nome certo.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

INDEX_NAME = "itens.json"
IMAGES_DIR = "imagens"
# Nomes curtos erram fácil ("Ore" x "Core"): só corrige nomes com tamanho mínimo.
FUZZY_MIN_LEN = 6
FUZZY_CUTOFF = 0.88


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


@dataclass(frozen=True)
class Recorded:
    name: str          # nome certo (canônico)
    rarity: str        # raridade mais vista desse item
    first_time: bool   # primeira vez que o catálogo vê esse item
    corrected: bool    # o nome lido foi corrigido


class Catalog:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.index_path = self.folder / INDEX_NAME
        self._lock = threading.Lock()
        self.items: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------ disco
    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.index_path.replace(self.index_path.with_suffix(".json.bak"))
            return
        for entry in data.get("items", []):
            if isinstance(entry, dict) and entry.get("name"):
                self.items[normalize(entry["name"])] = entry

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        ordered = sorted(self.items.values(), key=lambda e: e["name"].lower())
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"items": ordered}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.index_path)

    # ------------------------------------------------------------ busca
    def _find(self, name: str) -> tuple[dict | None, bool]:
        """Entrada do catálogo para esse nome lido; bool = foi por aproximação."""
        key = normalize(name)
        if not key:
            return None, False
        if key in self.items:
            return self.items[key], False
        for entry in self.items.values():
            if key in {normalize(a) for a in entry.get("aliases", [])}:
                return entry, False
        if len(key) >= FUZZY_MIN_LEN:
            close = difflib.get_close_matches(key, list(self.items), n=1, cutoff=FUZZY_CUTOFF)
            if close:
                return self.items[close[0]], True
        return None, False

    def resolve(self, name: str) -> str:
        """Nome certo para o que o OCR leu (ou o próprio nome, se for desconhecido)."""
        with self._lock:
            entry, _ = self._find(name)
            return entry["name"] if entry else name

    # ------------------------------------------------------------ registro
    def record(self, name: str, rarity: str, snapshot: np.ndarray | None,
               when: datetime | None = None) -> Recorded:
        when_iso = (when or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            entry, fuzzy = self._find(name)
            first_time = entry is None
            if entry is None:
                entry = {
                    "name": name,
                    "slug": slugify(name),
                    "image": None,
                    "rarity": rarity,
                    "rarity_votes": {},
                    "aliases": [],
                    "count": 0,
                    "first_seen": when_iso,
                    "last_seen": when_iso,
                }
                self.items[normalize(name)] = entry
            elif normalize(name) != normalize(entry["name"]) and name not in entry["aliases"]:
                entry["aliases"].append(name)
            votes = Counter(entry.get("rarity_votes", {}))
            votes[rarity] += 1
            entry["rarity_votes"] = dict(votes)
            entry["rarity"] = votes.most_common(1)[0][0]
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last_seen"] = when_iso
            if not entry.get("image") and snapshot is not None:
                entry["image"] = self._save_image(entry["slug"], snapshot)
            self.save()
            corrected = fuzzy or normalize(name) != normalize(entry["name"])
            return Recorded(entry["name"], entry["rarity"], first_time, corrected)

    def _save_image(self, slug: str, snapshot: np.ndarray) -> str | None:
        folder = self.folder / IMAGES_DIR
        folder.mkdir(parents=True, exist_ok=True)
        rel = f"{IMAGES_DIR}/{slug}.png"
        return rel if cv2.imwrite(str(self.folder / rel), snapshot) else None
