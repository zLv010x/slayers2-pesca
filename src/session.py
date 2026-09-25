"""Contagem da sessão: tempo rodando, itens pegos e um CSV para conferir depois.

A sessão fica guardada em disco (state_path) a cada item: fechar e abrir a macro continua de
onde parou. Só o botão Resetar apaga (forget) e começa do zero."""
from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import logbook

# Quantos itens ficam no histórico da tela (o CSV guarda todos). Folgado para uma noite
# inteira (~2000 drops): o filtro por raridade precisa achar os mythic antigos.
MAX_RECENT = 20_000
STATE_VERSION = 1


def format_elapsed(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


@dataclass
class Session:
    log_dir: Path | None = None
    state_path: Path | None = None                         # onde a sessão fica guardada
    counts: Counter = field(default_factory=Counter)      # nome -> quantidade somada
    rarities: Counter = field(default_factory=Counter)    # raridade -> nº de drops
    catches: int = 0                                       # nº de drops (cada coleta = 1)
    misses: int = 0                                        # minigames perdidos / sem aviso
    baits_used: Counter = field(default_factory=Counter)  # isca -> quantas gastou nesta sessão
    item_rarity: dict = field(default_factory=dict)       # item -> raridade (cor/ordem no overlay)
    last: list[tuple[str, str, int, str]] = field(default_factory=list)  # (hora, nome, qtd, raridade)
    _csv_path: Path | None = None
    _active_sec: float = 0.0            # tempo pescando nas rodadas anteriores
    _run_start: float | None = None     # início da rodada atual (None = parado)
    # record() roda na thread da pesca enquanto a aba Sessão lê a cada 1s na thread da
    # interface: sem isso, dá RuntimeError de dicionário mudando de tamanho na leitura.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @property
    def running(self) -> bool:
        return self._run_start is not None

    def start(self) -> None:
        with self._lock:
            if self._run_start is None:
                self._run_start = time.monotonic()

    def pause(self) -> None:
        with self._lock:
            if self._run_start is not None:
                self._active_sec += time.monotonic() - self._run_start
                self._run_start = None
        self._save_state()

    def elapsed_seconds(self) -> float:
        """Só o tempo em que a macro estava pescando (parado não conta)."""
        with self._lock:
            current = time.monotonic() - self._run_start if self._run_start is not None else 0.0
            return self._active_sec + current

    def elapsed_text(self) -> str:
        return format_elapsed(self.elapsed_seconds())

    def total_of(self, name: str) -> int:
        key = name.strip().lower()
        with self._lock:
            return sum(q for n, q in self.counts.items() if n.lower() == key)

    def record(self, name: str, quantity: int, rarity: str) -> None:
        now = datetime.now()
        with self._lock:
            self.catches += 1
            self.counts[name] += quantity
            self.rarities[rarity] += 1
            self.item_rarity[name] = rarity
            self.last.insert(0, (now.strftime("%H:%M:%S"), name, quantity, rarity))
            del self.last[MAX_RECENT:]
        self._append_csv(now, name, quantity, rarity)
        self._save_state()

    def recent(self, rarities: set[str] | None, limit: int | None = None) -> list[tuple[str, str, int, str]]:
        """Histórico (mais novo primeiro) só das raridades visíveis; None = todas. O filtro só
        esconde: tudo continua guardado e volta a aparecer quando a raridade é ligada."""
        with self._lock:
            items = [row for row in self.last if rarities is None or row[3] in rarities]
        return items[:limit] if limit else items

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1
        self._save_state()

    def record_bait(self, name: str) -> None:
        with self._lock:
            self.baits_used[name] += 1
        self._save_state()

    # ------------------------------------------------------------ guardar até resetar
    @classmethod
    def load(cls, log_dir: Path | None, state_path: Path | None) -> "Session":
        """Sessão guardada (a de antes de fechar a macro) ou uma nova, se não tiver."""
        s = cls(log_dir=log_dir, state_path=state_path)
        if state_path is None or not state_path.exists():
            return s
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            s._restore(data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logbook.get().warning("Sessão guardada estragada (%s): começando do zero", exc)
            try:
                state_path.replace(state_path.with_name(state_path.name + ".bak"))
            except OSError:
                pass
            return cls(log_dir=log_dir, state_path=state_path)
        return s

    def _restore(self, data: dict) -> None:
        if data.get("version") != STATE_VERSION:
            raise ValueError(f"versão {data.get('version')!r}")
        self.counts = Counter({str(k): int(v) for k, v in data["counts"].items()})
        self.rarities = Counter({str(k): int(v) for k, v in data["rarities"].items()})
        self.baits_used = Counter({str(k): int(v) for k, v in data.get("baits_used", {}).items()})
        self.catches, self.misses = int(data["catches"]), int(data["misses"])
        self.last = [(str(h), str(n), int(q), str(r)) for h, n, q, r in data["last"]][:MAX_RECENT]
        self.item_rarity = {n: r for _, n, _, r in reversed(self.last)}  # o mais novo vale
        self._active_sec = max(0.0, float(data.get("active_sec", 0.0)))
        csv_path = data.get("csv")
        self._csv_path = Path(csv_path) if csv_path and Path(csv_path).exists() else None

    def _save_state(self) -> None:
        """Guarda a sessão (atômico). Disco travado não pode derrubar o registro do item."""
        if self.state_path is None:
            return
        with self._lock:
            data = {
                "version": STATE_VERSION, "counts": dict(self.counts), "rarities": dict(self.rarities),
                "catches": self.catches, "misses": self.misses, "baits_used": dict(self.baits_used),
                "last": [list(row) for row in self.last], "active_sec": self.elapsed_seconds(),
                "csv": str(self._csv_path) if self._csv_path else None,
            }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logbook.get().warning("Não consegui guardar a sessão: %s", exc)

    def forget(self) -> None:
        """Resetar: apaga a sessão guardada (o CSV de cada sessão continua em logs/)."""
        if self.state_path is not None:
            try:
                self.state_path.unlink(missing_ok=True)
            except OSError as exc:
                logbook.get().warning("Não consegui apagar a sessão guardada: %s", exc)

    def item_rarities(self) -> dict[str, str]:
        with self._lock:
            return dict(self.item_rarity)

    def overlay_snapshot(self) -> tuple[str, Counter, Counter]:
        """Tempo, itens e iscas gastas (cópias: o overlay lê na thread da interface)."""
        with self._lock:
            return self.elapsed_text(), Counter(self.counts), Counter(self.baits_used)

    def _append_csv(self, when: datetime, name: str, quantity: int, rarity: str) -> None:
        # Escrita em disco (OneDrive/antivírus podem travar o arquivo): nunca pode derrubar o
        # registro do item, senão ele some do Discord antes de avisar.
        if self.log_dir is None:
            return
        try:
            if self._csv_path is None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                csv_path = self.log_dir / f"sessao-{stamp}.csv"
                with csv_path.open("w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(["hora", "item", "quantidade", "raridade"])
                self._csv_path = csv_path
            with self._csv_path.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([when.isoformat(timespec="seconds"), name, quantity, rarity])
        except OSError as exc:
            logbook.get().warning("Não consegui gravar o CSV da sessão: %s", exc)
