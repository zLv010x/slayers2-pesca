"""Contagem da sessão: tempo rodando, itens pegos e um CSV para conferir depois."""
from __future__ import annotations

import csv
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import logbook

# Quantos itens ficam no histórico da tela (o CSV guarda todos).
MAX_RECENT = 500


def format_elapsed(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


@dataclass
class Session:
    log_dir: Path | None = None
    counts: Counter = field(default_factory=Counter)      # nome -> quantidade somada
    rarities: Counter = field(default_factory=Counter)    # raridade -> nº de drops
    catches: int = 0                                       # nº de drops (cada coleta = 1)
    misses: int = 0                                        # minigames perdidos / sem aviso
    last: list[tuple[str, str, int, str]] = field(default_factory=list)  # (hora, nome, qtd, raridade)
    _csv_path: Path | None = None
    _active_sec: float = 0.0            # tempo pescando nas rodadas anteriores
    _run_start: float | None = None     # início da rodada atual (None = parado)
    # record() roda na thread da pesca enquanto a aba Sessão lê a cada 1s na thread da
    # interface: sem isso, dá RuntimeError de dicionário mudando de tamanho na leitura.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def running(self) -> bool:
        return self._run_start is not None

    def start(self) -> None:
        if self._run_start is None:
            self._run_start = time.monotonic()

    def pause(self) -> None:
        if self._run_start is not None:
            self._active_sec += time.monotonic() - self._run_start
            self._run_start = None

    def elapsed_seconds(self) -> float:
        """Só o tempo em que a macro estava pescando (parado não conta)."""
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
            self.last.insert(0, (now.strftime("%H:%M:%S"), name, quantity, rarity))
            del self.last[MAX_RECENT:]
        self._append_csv(now, name, quantity, rarity)

    def recent(self, rarities: set[str], limit: int | None = None) -> list[tuple[str, str, int, str]]:
        """Histórico (mais novo primeiro) só das raridades escolhidas; conjunto vazio = todas."""
        with self._lock:
            items = [row for row in self.last if not rarities or row[3] in rarities]
        return items[:limit] if limit else items

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

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
