"""Catálogo de itens em duas camadas.

- catalogo/        compartilhado (vai para o GitHub). A macro só LÊ essa pasta.
- catalogo_local/  deste PC (fora do git). Itens que ainda não estão no
                   compartilhado entram aqui, com imagem; e as contagens pessoais.

Cada item tem uma imagem só (a da primeira vez) e uma entrada no itens.json.
A macro usa o catálogo para:
- saber se o item já é conhecido (se não for, é "primeiro no catálogo");
- corrigir erros do OCR comparando com os nomes conhecidos ("Golden Fisn" -> "Golden Fish");
- dar a FICHA do item para o aviso (Discord e janela): nome certo, imagem e raridade.
  A raridade escrita no compartilhado manda (dá para corrigir à mão no itens.json); item que
  ainda não está lá usa a raridade mais vista nas leituras da cor;
- barrar nome que não existe: nome desconhecido só vira item novo se parecer nome de item.
  Lixo da tela ("xg•.ollec" do botão Collect, "xlv" do "x1") nunca entra; nome desconfiado
  (pedaço de um nome conhecido, sujo, ou lido por uma variante só do OCR) fica AGUARDANDO no
  local, sem aparecer, e entra na PENDING_PROMOTE-ésima vez: item novo de verdade não some.

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
# Nome longo com tamanho quase igual aceita um pouco mais de diferença ("Golden FEh", "Crustadofi",
# "KrathLtlon" ficam em 0,84). Tamanho bem diferente não: "Big Zebra Fish" seria outro item.
FUZZY_CUTOFF_LONG = 0.84
FUZZY_LONG_LEN = 8
FUZZY_LONG_MAX_LEN_DIFF = 2
FUZZY_MARGIN = 0.05          # dois nomes quase iguais ao lido: não chuta nenhum
# Sujeira do ícone grudada antes do nome ("Jzebra Fish", "GNOuwFish", "8 N Metal Scraps", "ggcoral").
AFFIX_MIN_LEN = 5
AFFIX_MAX_JUNK = 2
# Começo do nome cortado (aviso surgindo/apagando): "ra Fish" = Zebra Fish sem "Zeb", "thulon".
CUT_MIN_LEN = 6
CUT_MAX_MISSING = 3
TIDY_MAX_PASSES = 3
# O arrumar só junta por semelhança (e só apaga pedaço de nome) o que foi visto poucas vezes:
# "Anglerfish" pego 12 vezes é outro peixe, não "Angelfish" lido errado.
TIDY_RARE_COUNT = 2
TIDY_RARE_SHARE = 0.10
TIDY_BACKUP_NAME = "itens.antes-de-arrumar.json"
EXACT_HOWS = ("exact", "fixed", "alias", "shape", "affix", "cut")  # jeitos de achar que não são chute
SHARED_FIELDS = ("name", "slug", "image", "rarity", "rarity_votes", "aliases")
RARITIES = ("common", "rare", "epic", "legendary", "mythic")
# Nome de item tem pelo menos 3 letras ("Ore"): "6d" (prazo dos códigos no menu principal)
# e textos da própria tela ("Collect", "item", a etiqueta "NEW!") não são itens.
MIN_NAME_LETTERS = 3
IGNORED_NAMES = {"item", "collect", "new"}
PROMPT_WORD = "collect"      # o botão "Collect" lido torto ("Cotlect", "lollect")
PROMPT_CUTOFF = 0.8
# Pedaço do botão com sujeira ("xg•.ollec" -> "xgollec"): 5-6 letras seguidas de "collect" e
# até 2 a mais. Com 4 não ("Pollen", "Select" podem ser itens); a palavra inteira também não
# ("Collector").
PROMPT_PIECE_MIN = 5
PROMPT_PIECE_MAX_EXTRA = 2
# O "x1" embaixo do nome lido como nome ("xlv", "xl -SE", "XXI"); "Xiphos" (6 letras) passa.
QTY_LIKE_RX = re.compile(r"^\W*[xX×]{1,2}\s*[lI1i|]")
QTY_LIKE_MAX_LETTERS = 4
VOWELS = frozenset("aeiouy")  # nome de item sempre tem vogal ("mxl", "XC. c.llé.:l" não)
# Nome desconhecido desconfiado vira item novo quando for visto tantas vezes (fica aguardando).
PENDING_PROMOTE = 3
# Nome novo "limpo": palavras de 3+ letras com Maiúscula+minúscula no começo ("OuwFish", "Ore";
# "FIF", "ROre" não), apóstrofo só no "'s" do fim ("Clovu'll" não), ou número. ASCII.
NAME_WORD_RX = re.compile(r"[A-Z][a-z][A-Za-z]+(?:'s)?|[0-9]+")
NAME_SMALL_WORDS = frozenset({"of", "the", "and", "a", "an", "on", "in", "to",
                              "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"})
# Sujeira minúscula grudada antes da inicial maiúscula de um item NOVO ("zMythic Refinement Ore").
# Só no nome do item novo: em leitura cortada ("uwFvvesh" = OuwFwesh sem o "O") são letras de verdade.
LOWER_JUNK_RX = re.compile(r"^[a-z]{1,2}(?=[A-Z][a-z])")
# Trocas típicas do OCR do Windows nesta fonte: o "w" vira "v.t", "vt.t", "v.r", "v•j", "vv".
OCR_FIXES = (
    (re.compile(r"v(?:t?[^\w\s]+[tjri]|v)", re.IGNORECASE), "w"),
    (re.compile(r"\$"), "s"),
    (re.compile(r"0"), "o"),
    (re.compile(r"1"), "l"),
)
# "Esqueleto" do nome: letras que o OCR confunde viram a mesma, nos DOIS lados da comparação
# ("C r LI stado" -> "crustado", "Crustaclon" -> "crustadon", "KrathLtlon" -> "krathulon").
SHAPE_RULES = (
    (re.compile(r"[il|!]"), "l"),
    (re.compile(r"rn"), "m"),
    (re.compile(r"cl"), "d"),
    (re.compile(r"l[lt]"), "u"),
    (re.compile(r"5"), "s"),
)


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


RARITY_PREFIX = re.compile(r"^\W*\w?(mythic|legendary|epic|rare|common)\s+", re.IGNORECASE)


def strip_rarity(name: str) -> str:
    """ "zMythic Refinement Ore" -> "Refinement Ore": o aviso às vezes vem com a raridade na
    frente (usuário 25/09: é o mesmo item)."""
    return RARITY_PREFIX.sub("", name)


def fix_ocr(name: str) -> str:
    for pattern, repl in OCR_FIXES:
        name = pattern.sub(repl, name)
    return name


def shape_key(name: str) -> str:
    shape = re.sub(r"[^a-z0-9|!]", "", fix_ocr(name).lower())
    for pattern, repl in SHAPE_RULES:
        shape = pattern.sub(repl, shape)
    return shape


def _is_prompt_piece(key: str) -> bool:
    """Pedaço do botão "Collect": "oll", "xgollec" (sujeira + "ollec")."""
    if len(key) >= MIN_NAME_LETTERS and key in PROMPT_WORD:
        return True
    match = difflib.SequenceMatcher(None, key, PROMPT_WORD).find_longest_match(0, len(key), 0, len(PROMPT_WORD))
    return PROMPT_PIECE_MIN <= match.size < len(PROMPT_WORD) and len(key) - match.size <= PROMPT_PIECE_MAX_EXTRA


def plausible_name(name: str) -> bool:
    """Pode ser nome de item? Barra o lixo da tela: botão Collect, selo NEW!, "x1", "6d"."""
    letters = re.sub(r"[^A-Za-z]", "", name)
    key = normalize(name)
    if len(letters) < MIN_NAME_LETTERS or key in IGNORED_NAMES:
        return False
    if not VOWELS & set(letters.lower()):
        return False
    if QTY_LIKE_RX.match(name) and len(letters) <= QTY_LIKE_MAX_LETTERS:
        return False
    if _is_prompt_piece(key):
        return False
    if len(key) > len(PROMPT_WORD) + 1:
        return True  # "Collector"/"Collected" podem ser itens
    return difflib.SequenceMatcher(None, key, PROMPT_WORD).ratio() < PROMPT_CUTOFF


def looks_like_item_name(name: str) -> bool:
    """Nome limpo como os do jogo ("Shotgun Schematic", "OuwFish"): sem símbolo, letra solta,
    número grudado ou inicial minúscula ("TY. lon", "inent C", "C10i.*v111 Fish", "ont Ores")."""
    words = [w for w in re.split(r"[ -]+", name.strip()) if w]
    return (bool(words) and name.isascii() and words[0][0].isupper()
            and all(NAME_WORD_RX.fullmatch(w) or w in NAME_SMALL_WORDS for w in words))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


@dataclass(frozen=True)
class Recorded:
    name: str          # nome certo (canônico)
    rarity: str        # raridade mais vista desse item
    first_time: bool   # item que não estava em nenhum catálogo
    corrected: bool    # o nome lido foi corrigido
    accepted: bool = True  # False = lixo ou nome aguardando confirmar: não mostrar nem contar
    pending: int = 0       # nome aguardando: quantas vezes já foi visto (de PENDING_PROMOTE)


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


def _affix_match(key: str, entries: dict[str, dict]) -> str | None:
    """Nome conhecido com até AFFIX_MAX_JUNK letras de sujeira antes ("jzebrafish")."""
    fits = [k for k in entries
            if len(k) >= AFFIX_MIN_LEN and key.endswith(k) and 0 < len(key) - len(k) <= AFFIX_MAX_JUNK]
    return max(fits, key=len, default=None)


def _cut_match(key: str, entries: dict[str, dict]) -> str | None:
    """Um só nome conhecido termina com o que foi lido, faltando até CUT_MAX_MISSING letras.
    A primeira letra do pedaço pode vir trocada (a borda do corte: "Dra Fish" = "(Ze)bra Fish")."""
    for tail in (key, key[1:]):
        if len(tail) < CUT_MIN_LEN:
            continue
        fits = [k for k in entries if k.endswith(tail) and 0 < len(k) - len(tail) <= CUT_MAX_MISSING]
        if len(fits) == 1:
            return fits[0]
    return None


def _shape_table(entries: dict[str, dict]) -> dict[str, str]:
    """{esqueleto: chave}; esqueleto de dois itens ao mesmo tempo fica de fora (ambíguo)."""
    table: dict[str, str | None] = {}
    for key, entry in entries.items():
        shape = shape_key(entry.get("name", key))
        table[shape] = None if shape in table and table[shape] != key else key
    return {shape: key for shape, key in table.items() if shape and key}


def _fuzzy_match(key: str, entries: dict[str, dict]) -> tuple[str, bool] | None:
    """Nome conhecido parecido; bool = só passou no corte folgado (nome longo)."""
    if len(key) < FUZZY_MIN_LEN or not entries:
        return None
    scored = sorted(((difflib.SequenceMatcher(None, key, k).ratio(), k) for k in entries), reverse=True)
    best, found = scored[0]
    near_len = abs(len(key) - len(found)) <= FUZZY_LONG_MAX_LEN_DIFF
    cutoff = FUZZY_CUTOFF_LONG if near_len and max(len(key), len(found)) >= FUZZY_LONG_LEN else FUZZY_CUTOFF
    if best < cutoff:
        return None
    if len(scored) > 1 and best - scored[1][0] < FUZZY_MARGIN:
        return None  # dois itens quase iguais ao que foi lido: não dá para saber qual
    return found, best < FUZZY_CUTOFF


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
        """Itens de verdade: o compartilhado e o local sem os nomes aguardando e sem o lixo que
        versões antigas gravaram (senão eles puxam as leituras parecidas: "bra Fish" -> "ra Fish")."""
        local = {k: e for k, e in self.local.items()
                 if "pending" not in e and plausible_name(e.get("name", ""))}
        return {**local, **self.shared}

    def _find(self, name: str, exclude: str | None = None) -> tuple[str | None, str | None]:
        """Chave do item para esse nome lido e como achou: "exact", "fixed" (trocas do OCR
        desfeitas), "alias", "shape" (mesmo esqueleto), "affix" (sujeira antes do nome), "cut"
        (começo cortado), "fuzzy" ou "fuzzy_relaxed"."""
        keys = [k for k in dict.fromkeys((normalize(name), normalize(fix_ocr(name)),
                                          normalize(strip_rarity(name)))) if k]
        if not keys:
            return None, None
        entries = {k: e for k, e in self._entries().items() if k != exclude}
        for key in keys:
            if key in entries:
                return key, "exact" if key == keys[0] else "fixed"
        for key in keys:
            for k, entry in entries.items():
                if key in {normalize(a) for a in entry.get("aliases", [])}:
                    return k, "alias"
        shapes = _shape_table(entries)
        shape = shape_key(name)
        if shape in shapes:
            return shapes[shape], "shape"
        for how, match in (("affix", _affix_match), ("cut", _cut_match)):
            for key in keys:
                found = match(key, entries)
                if found:
                    return found, how
        for key, table in [*((k, entries) for k in keys), (shape, shapes)]:
            fuzzy = _fuzzy_match(key, table)
            if fuzzy:
                found = fuzzy[0] if table is entries else shapes[fuzzy[0]]
                return found, "fuzzy_relaxed" if fuzzy[1] else "fuzzy"
        return None, None

    def _verdict(self, name: str, confirmed: bool) -> str:
        """Nome que o catálogo não conhece: "junk" (nunca é item), "pending" (desconfiado:
        aguarda ser visto de novo) ou "new" (item novo na hora)."""
        if not plausible_name(name):
            return "junk"
        holders = self._holders(name)
        if len(holders) >= 2:
            return "junk"  # pedaço de vários nomes ("Fish", "ouw"): não dá para saber qual
        if holders or not confirmed or not looks_like_item_name(name):
            return "pending"
        return "new"

    def _holders(self, name: str) -> set[str]:
        """Itens conhecidos dos quais o nome lido é só um pedaço ("Zebra", "Thread", "Fish")."""
        parts = {p for p in (normalize(name), normalize(fix_ocr(name)), shape_key(name))
                 if len(p) >= MIN_NAME_LETTERS}
        holders = set()
        for key, entry in self._entries().items():
            whole = {key, shape_key(entry.get("name", key))}
            if any(part in w and part not in whole for part in parts for w in whole):
                holders.add(key)
        return holders

    def _pending_seen(self, name: str) -> int:
        """Conta mais uma vez o nome aguardando; devolve quantas vezes já foi visto."""
        entry = self.local.setdefault(normalize(name), {**_new_entry(name), "pending": 0})
        if "pending" not in entry:
            return PENDING_PROMOTE  # já é item (lixo antigo com a mesma chave): segue normal
        entry["pending"] += 1
        return entry["pending"]

    def _promote(self, key: str) -> None:
        self.local[key].pop("pending", None)

    def _save_local(self) -> None:
        try:
            _save_index(self.local_dir / INDEX_NAME, self.local)
        except OSError as exc:
            # disco travado (OneDrive/antivírus) não pode abortar o registro antes do Discord
            # ser avisado: só loga e segue (a próxima gravação bem-sucedida já corrige o arquivo).
            logbook.get().warning("Não consegui salvar o catálogo local: %s", exc)

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
               when: datetime | None = None, confirmed: bool = True) -> Recorded:
        """confirmed=False: só uma variante do OCR leu esse nome (se for desconhecido, aguarda)."""
        when_iso = (when or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            key, how = self._find(name)
            new_name = LOWER_JUNK_RX.sub("", name)  # nome do item novo, sem a sujeira do ícone
            if key is None and new_name != name:
                key, how = self._find(new_name)
            first_time = key is None
            if key is None:
                verdict = self._verdict(new_name, confirmed)
                if verdict == "junk":
                    return Recorded(name, rarity, False, False, accepted=False)
                key = normalize(new_name)
                if verdict == "pending":
                    seen = self._pending_seen(new_name)
                    if seen < PENDING_PROMOTE:
                        self._save_local()
                        return Recorded(name, rarity, False, False, accepted=False, pending=seen)
                    self._promote(key)
            canonical_name = self._canonical(key)["name"] if not first_time else new_name
            local = self.local.setdefault(key, _new_entry(canonical_name))
            local.setdefault("count", 0)
            local.setdefault("first_seen", when_iso)
            # chute folgado vale na hora, mas não vira apelido gravado: se for um item novo de
            # verdade, ele ficaria preso ao nome errado (e iria para os amigos no publicar)
            if (how != "fuzzy_relaxed" and normalize(name) != key and name not in local["aliases"]
                    and not self._is_known_alias(key, name)):
                local["aliases"].append(name)
            votes = Counter(local.get("rarity_votes", {}))
            votes[rarity] += 1
            local["rarity_votes"] = dict(votes)
            local["count"] += 1
            local["last_seen"] = when_iso
            in_shared_with_image = bool(self.shared.get(key, {}).get("image"))
            if not in_shared_with_image and not local.get("image") and snapshot is not None:
                local["image"] = self._save_image(self.local_dir, local["slug"], snapshot)
            best = self._fixed_rarity(key) or self._votes(key).most_common(1)[0][0]
            local["rarity"] = best
            self._save_local()
            corrected = how not in (None, "exact") or normalize(name) != key
            return Recorded(canonical_name, best, first_time, corrected)

    def prices(self) -> dict[str, int]:
        """Preço de venda da unidade de cada item ({nome certo: preço}), da ficha. Inválido fica de fora."""
        with self._lock:
            entries = self._entries()
        out = {}
        for entry in entries.values():
            price = entry.get("price")
            if isinstance(price, int) and not isinstance(price, bool) and price >= 0:
                out[entry["name"]] = price
        return out

    def _fixed_rarity(self, key: str) -> str | None:
        """Raridade escrita na ficha do compartilhado (None = não tem ou está errada)."""
        rarity = self.shared.get(key, {}).get("rarity")
        return rarity if rarity in RARITIES else None

    def card_image(self, name: str) -> np.ndarray | None:
        """Imagem da ficha do item (a do compartilhado; senão a do local). None = sem imagem."""
        with self._lock:
            key, _ = self._find(name)
            if key is None:
                return None
            places = ((self.shared_dir, self.shared.get(key, {})), (self.local_dir, self.local.get(key, {})))
        for folder, entry in places:
            if entry.get("image"):
                img = cv2.imread(str(folder / entry["image"]))
                if img is not None:
                    return img
        return None

    def _is_known_alias(self, key: str, name: str) -> bool:
        return name in self.shared.get(key, {}).get("aliases", [])

    @staticmethod
    def _save_image(folder: Path, slug: str, snapshot: np.ndarray) -> str | None:
        (folder / IMAGES_DIR).mkdir(parents=True, exist_ok=True)
        rel = f"{IMAGES_DIR}/{slug}.png"
        return rel if cv2.imwrite(str(folder / rel), snapshot) else None

    # ------------------------------------------------------------ arrumar (só o local)
    def tidy(self) -> list[tuple[str, str | None]]:
        """Arruma o catálogo local com as regras de hoje: leitura errada de um item conhecido
        entra no item certo (somando contagem e votos) e lixo do OCR sai, com a imagem.
        Devolve [(nome antigo, nome certo ou None = apagado)]."""
        changes: list[tuple[str, str | None]] = []
        with self._lock:
            for _ in range(TIDY_MAX_PASSES):  # juntar uma leitura pode destravar outra (dois parecidos)
                done = self._tidy_pass()
                changes += done
                if not done:
                    break
            if changes:
                try:
                    self._backup_local_index()
                    _save_index(self.local_dir / INDEX_NAME, self.local)
                except OSError as exc:
                    logbook.get().warning("Não consegui salvar o catálogo local arrumado: %s", exc)
        return changes

    def _tidy_pass(self) -> list[tuple[str, str | None]]:
        changes: list[tuple[str, str | None]] = []
        # só o que não está no compartilhado; leituras raras primeiro, para entrarem no nome certo
        order = sorted((k for k in self.local if k not in self.shared),
                       key=lambda k: (self.local[k].get("count", 0), k))
        for key in order:
            entry = self.local.get(key)
            if entry is None:
                continue
            name = entry.get("name", "")
            if not plausible_name(name):
                self._drop_local(key)
                changes.append((name, None))
                continue
            if "pending" in entry:
                continue  # aguardando confirmar: não é item ainda, não junta em nada
            target, how = self._find(name, exclude=key)
            if target is not None:
                if self._can_absorb(target, key) and (how in EXACT_HOWS or self._rare_read(key, target)):
                    self._merge_local(key, target)
                    changes.append((name, self._canonical(target)["name"]))
            elif ((self._is_partial(key) and self._count(key) <= TIDY_RARE_COUNT)
                  or (self._count(key) < PENDING_PROMOTE and self._suspicious(name, key))):
                self._drop_local(key)
                changes.append((name, None))
        return changes

    def _suspicious(self, name: str, key: str) -> bool:
        """Item antigo do local que hoje ficaria aguardando: sujo ("4cpilk Thread", "Clou'll Fish")
        ou pedaço de um nome conhecido ("Thread"). Visto pouco: é lixo de versão antiga."""
        trimmed = LOWER_JUNK_RX.sub("", name)
        dirty = not looks_like_item_name(trimmed) and re.search(r"[^A-Za-z ]", trimmed) is not None
        return dirty or bool(self._holders(trimmed) - {key})

    def _count(self, key: str) -> int:
        return self.local.get(key, {}).get("count", 0)

    def _rare_read(self, key: str, target: str) -> bool:
        """Leitura vista poucas vezes (perto do item certo): pode ser juntada por semelhança."""
        n = self._count(key)
        return n <= TIDY_RARE_COUNT or n <= TIDY_RARE_SHARE * self._count(target)

    def _backup_local_index(self) -> None:
        index = self.local_dir / INDEX_NAME
        if index.exists():
            shutil.copy2(index, self.local_dir / TIDY_BACKUP_NAME)

    def _is_partial(self, key: str) -> bool:
        """Pedaço de um nome conhecido ("ouw" de OuwFish, "Fish"): leitura cortada, não item."""
        return len(key) < FUZZY_MIN_LEN and any(
            key in k for k in self._entries() if k != key and len(k) >= FUZZY_MIN_LEN)

    def _can_absorb(self, target: str, key: str) -> bool:
        """Só junta no nome mais visto; no empate, no mais completo (leitura cortada perde letras)."""
        if target in self.shared:
            return True
        rank = lambda k: (self.local[k].get("count", 0), len(k))  # noqa: E731
        return rank(target) > rank(key)

    def _merge_local(self, src_key: str, dst_key: str) -> None:
        src = self.local.pop(src_key)
        dst = self.local.setdefault(dst_key, _new_entry(self._canonical_or(dst_key, src)["name"]))
        dst["count"] = dst.get("count", 0) + src.get("count", 0)
        dst["rarity_votes"] = dict(Counter(dst.get("rarity_votes", {})) + Counter(src.get("rarity_votes", {})))
        for alias in [src.get("name", ""), *src.get("aliases", [])]:
            if (alias and normalize(alias) != dst_key and alias not in dst["aliases"]
                    and not self._is_known_alias(dst_key, alias)):
                dst["aliases"].append(alias)
        for field, pick in (("first_seen", min), ("last_seen", max)):
            seen = [v for v in (dst.get(field), src.get(field)) if v]
            if seen:
                dst[field] = pick(seen)
        votes = self._votes(dst_key)
        if votes:
            dst["rarity"] = votes.most_common(1)[0][0]
        self._move_image(src, dst, dst_key)

    def _canonical_or(self, key: str, fallback: dict) -> dict:
        return self.shared.get(key) or self.local.get(key) or fallback

    def _move_image(self, src: dict, dst: dict, dst_key: str) -> None:
        """A imagem da leitura errada vira a do item certo se ele não tinha nenhuma; senão sai."""
        if not src.get("image"):
            return
        path = self.local_dir / src["image"]
        has_image = dst.get("image") or self.shared.get(dst_key, {}).get("image")
        target = self.local_dir / IMAGES_DIR / f"{dst['slug']}.png"
        try:
            if not has_image and path.exists() and not target.exists():
                path.replace(target)
                dst["image"] = f"{IMAGES_DIR}/{target.name}"
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            logbook.get().warning("Não consegui mexer na imagem %s: %s", path.name, exc)

    def _drop_local(self, key: str) -> None:
        entry = self.local.pop(key)
        if entry.get("image"):
            try:
                (self.local_dir / entry["image"]).unlink(missing_ok=True)
            except OSError as exc:
                logbook.get().warning("Não consegui apagar a imagem %s: %s", entry["image"], exc)

    # ------------------------------------------------------------ publicar
    def publish(self) -> list[str]:
        """Junta o catálogo local no compartilhado. Devolve os itens novos no compartilhado."""
        added: list[str] = []
        with self._lock:
            for key, local in self.local.items():
                if "pending" in local or not plausible_name(local.get("name", "")):
                    continue  # lixo de OCR / nome aguardando confirmar: não vai para os amigos
                shared = self.shared.get(key)
                if shared is None:
                    shared = {f: local.get(f) for f in SHARED_FIELDS}
                    shared["rarity_votes"], shared["aliases"], shared["image"] = {}, [], None
                    self.shared[key] = shared
                    added.append(local["name"])
                votes = Counter(shared.get("rarity_votes", {})) + Counter(local.get("rarity_votes", {}))
                shared["rarity_votes"] = dict(votes)
                if shared.get("rarity") not in RARITIES:  # a ficha já tem raridade: não troca
                    shared["rarity"] = votes.most_common(1)[0][0] if votes else None
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
    cat = Catalog(root / "catalogo", root / "catalogo_local")
    cat.tidy()  # leituras erradas antigas entram no item certo antes de ir para os amigos
    new = cat.publish()
    print(f"{len(new)} item(ns) novo(s) no catálogo compartilhado: {', '.join(new) or '-'}")
