"""Catálogo de itens em duas camadas.

- catalogo/        compartilhado (vai para o GitHub). A macro só LÊ essa pasta.
- catalogo_local/  deste PC (fora do git). Itens que ainda não estão no
                   compartilhado entram aqui, com imagem; e as contagens pessoais.

Cada item tem uma imagem só (a da primeira vez) e uma entrada no itens.json.
A macro usa o catálogo para:
- saber se o item já é conhecido (se não for, é "primeiro no catálogo");
- corrigir erros do OCR comparando com os nomes conhecidos ("Golden Fisn" -> "Golden Fish");
- usar a raridade mais vista daquele item em vez de confiar só na cor da vez.

`python src/catalog.py publicar` junta o catalogo_local no compartilhado.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import sys
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import logbook

INDEX_NAME = "itens.json"
IMAGES_DIR = "imagens"
# Nomes curtos erram fácil ("Ore" x "Core"): só corrige nomes com tamanho mínimo.
FUZZY_MIN_LEN = 6
FUZZY_CUTOFF = 0.88
SHARED_FIELDS = ("name", "slug", "image", "rarity", "rarity_votes", "aliases")
# Nome de item tem pelo menos 3 letras ("Ore"): "6d" (prazo dos códigos no menu principal)
# e textos da própria tela ("Collect", "item") não são itens.
MIN_NAME_LETTERS = 3
IGNORED_NAMES = {"item", "collect"}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def plausible_name(name: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", name)
    return len(letters) >= MIN_NAME_LETTERS and name.strip().lower() not in IGNORED_NAMES


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


@dataclass(frozen=True)
class Recorded:
    name: str          # nome certo (canônico)
    rarity: str        # raridade mais vista desse item
    first_time: bool   # item que não estava em nenhum catálogo
    corrected: bool    # o nome lido foi corrigido


def _load_index(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.replace(path.with_suffix(".json.bak"))
        return {}
    return {normalize(e["name"]): e for e in data.get("items", []) if isinstance(e, dict) and e.get("name")}


def _save_index(path: Path, items: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(items.values(), key=lambda e: e["name"].lower())
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"items": ordered}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _new_entry(name: str) -> dict:
    return {"name": name, "slug": slugify(name), "image": None, "rarity": None,
            "rarity_votes": {}, "aliases": []}


class Catalog:
    def __init__(self, shared_dir: Path, local_dir: Path | None = None) -> None:
        self.shared_dir = Path(shared_dir)
        self.local_dir = Path(local_dir) if local_dir else self.shared_dir.with_name(self.shared_dir.name + "_local")
        self._lock = threading.Lock()
        self.shared = _load_index(self.shared_dir / INDEX_NAME)
        self.local = _load_index(self.local_dir / INDEX_NAME)

    # ------------------------------------------------------------ consulta
    def knows(self, name: str) -> bool:
        """O item (ou uma leitura parecida) já está em algum catálogo?"""
        with self._lock:
            return self._find(name)[0] is not None

    def _entries(self) -> dict[str, dict]:
        return {**self.local, **self.shared}

    def _find(self, name: str) -> tuple[str | None, bool]:
        """Chave do item para esse nome lido; bool = achou por aproximação."""
        key = normalize(name)
        if not key:
            return None, False
        entries = self._entries()
        if key in entries:
            return key, False
        for k, entry in entries.items():
            if key in {normalize(a) for a in entry.get("aliases", [])}:
                return k, False
        if len(key) >= FUZZY_MIN_LEN:
            close = difflib.get_close_matches(key, list(entries), n=1, cutoff=FUZZY_CUTOFF)
            if close:
                return close[0], True
        return None, False

    def _canonical(self, key: str) -> dict:
        return self.shared.get(key) or self.local[key]

    def _votes(self, key: str) -> Counter:
        return (Counter(self.shared.get(key, {}).get("rarity_votes", {}))
                + Counter(self.local.get(key, {}).get("rarity_votes", {})))

    def resolve(self, name: str) -> str:
        """Nome certo para o que o OCR leu (ou o próprio nome, se for desconhecido)."""
        with self._lock:
            key, _ = self._find(name)
            return self._canonical(key)["name"] if key else name

    # ------------------------------------------------------------ registro (só no local)
    def record(self, name: str, rarity: str, snapshot: np.ndarray | None,
               when: datetime | None = None) -> Recorded:
        when_iso = (when or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            key, fuzzy = self._find(name)
            first_time = key is None
            if key is None:
                key = normalize(name)
            canonical_name = self._canonical(key)["name"] if not first_time else name
            local = self.local.setdefault(key, _new_entry(canonical_name))
            local.setdefault("count", 0)
            local.setdefault("first_seen", when_iso)
            if normalize(name) != key and name not in local["aliases"] and not self._is_known_alias(key, name):
                local["aliases"].append(name)
            votes = Counter(local.get("rarity_votes", {}))
            votes[rarity] += 1
            local["rarity_votes"] = dict(votes)
            local["count"] += 1
            local["last_seen"] = when_iso
            in_shared_with_image = bool(self.shared.get(key, {}).get("image"))
            if not in_shared_with_image and not local.get("image") and snapshot is not None:
                local["image"] = self._save_image(self.local_dir, local["slug"], snapshot)
            best = self._votes(key).most_common(1)[0][0]
            local["rarity"] = best
            try:
                _save_index(self.local_dir / INDEX_NAME, self.local)
            except OSError as exc:
                # disco travado (OneDrive/antivírus) não pode abortar o registro antes do Discord
                # ser avisado: só loga e segue (a próxima gravação bem-sucedida já corrige o arquivo).
                logbook.get().warning("Não consegui salvar o catálogo local: %s", exc)
            corrected = fuzzy or normalize(name) != key
            return Recorded(canonical_name, best, first_time, corrected)

    def _is_known_alias(self, key: str, name: str) -> bool:
        return name in self.shared.get(key, {}).get("aliases", [])

    @staticmethod
    def _save_image(folder: Path, slug: str, snapshot: np.ndarray) -> str | None:
        (folder / IMAGES_DIR).mkdir(parents=True, exist_ok=True)
        rel = f"{IMAGES_DIR}/{slug}.png"
        return rel if cv2.imwrite(str(folder / rel), snapshot) else None

    # ------------------------------------------------------------ publicar
    def publish(self) -> list[str]:
        """Junta o catálogo local no compartilhado. Devolve os itens novos no compartilhado."""
        added: list[str] = []
        with self._lock:
            for key, local in self.local.items():
                if not plausible_name(local.get("name", "")):
                    continue  # lixo de OCR que entrou antes do filtro: não vai para os amigos
                shared = self.shared.get(key)
                if shared is None:
                    shared = {f: local.get(f) for f in SHARED_FIELDS}
                    shared["rarity_votes"], shared["aliases"], shared["image"] = {}, [], None
                    self.shared[key] = shared
                    added.append(local["name"])
                votes = Counter(shared.get("rarity_votes", {})) + Counter(local.get("rarity_votes", {}))
                shared["rarity_votes"] = dict(votes)
                shared["rarity"] = votes.most_common(1)[0][0] if votes else shared.get("rarity")
                shared["aliases"] = sorted(set(shared.get("aliases", [])) | set(local.get("aliases", [])))
                if not shared.get("image") and local.get("image"):
                    src = self.local_dir / local["image"]
                    if src.exists():
                        (self.shared_dir / IMAGES_DIR).mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, self.shared_dir / local["image"])
                        shared["image"] = local["image"]
                # o que foi publicado sai do local (senão contaria em dobro); ficam as contagens
                local["rarity_votes"], local["aliases"] = {}, []
            _save_index(self.shared_dir / INDEX_NAME, self.shared)
            _save_index(self.local_dir / INDEX_NAME, self.local)
        return added


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    if sys.argv[1:] != ["publicar"]:
        sys.exit("uso: python src/catalog.py publicar")
    new = Catalog(root / "catalogo", root / "catalogo_local").publish()
    print(f"{len(new)} item(ns) novo(s) no catálogo compartilhado: {', '.join(new) or '-'}")
