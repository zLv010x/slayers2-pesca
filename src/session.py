"""Contagem da sessão: tempo rodando, itens pegos e um CSV para conferir depois."""
from __future__ import annotations

import csv
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

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
        return sum(q for n, q in self.counts.items() if n.lower() == key)

    def record(self, name: str, quantity: int, rarity: str) -> None:
        now = datetime.now()
        self.catches += 1
        self.counts[name] += quantity
        self.rarities[rarity] += 1
        self.last.insert(0, (now.strftime("%H:%M:%S"), name, quantity, rarity))
        del self.last[MAX_RECENT:]
        self._append_csv(now, name, quantity, rarity)

    def recent(self, rarities: set[str], limit: int | None = None) -> list[tuple[str, str, int, str]]:
        """Histórico (mais novo primeiro) só das raridades escolhidas; conjunto vazio = todas."""
        items = [row for row in self.last if not rarities or row[3] in rarities]
        return items[:limit] if limit else items

    def record_miss(self) -> None:
        self.misses += 1

    def _append_csv(self, when: datetime, name: str, quantity: int, rarity: str) -> None:
        if self.log_dir is None:
            return
        if self._csv_path is None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            self._csv_path = self.log_dir / f"sessao-{stamp}.csv"
            with self._csv_path.open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["hora", "item", "quantidade", "raridade"])
        with self._csv_path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([when.isoformat(timespec="seconds"), name, quantity, rarity])
