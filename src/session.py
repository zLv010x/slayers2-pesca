"""Contagem da sessão: tempo rodando, itens pegos e um CSV para conferir depois."""
from __future__ import annotations

import csv
import re
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
    baits_used: Counter = field(default_factory=Counter)  # isca -> quantas gastou nesta sessão
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

    def tracked_breakdown(self, word: str) -> dict[str, int]:
        """Itens com essa palavra no nome e quanto de cada ("Ore" -> Ore, Refinement Ore)."""
        word = word.strip()
        if not word:
            return {}
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        with self._lock:
            found = {n: q for n, q in self.counts.items() if pattern.search(n)}
        return dict(sorted(found.items(), key=lambda kv: -kv[1]))

    def record(self, name: str, quantity: int, rarity: str) -> None:
        now = datetime.now()
        with self._lock:
            self.catches += 1
            self.counts[name] += quantity
            self.rarities[rarity] += 1
            self.last.insert(0, (now.strftime("%H:%M:%S"), name, quantity, rarity))
            del self.last[MAX_RECENT:]
        self._append_csv(now, name, quantity, rarity)

    def recent(self, rarities: set[str] | None, limit: int | None = None) -> list[tuple[str, str, int, str]]:
        """Histórico (mais novo primeiro) só das raridades visíveis; None = todas. O filtro só
        esconde: tudo continua guardado e volta a aparecer quando a raridade é ligada."""
        with self._lock:
            items = [row for row in self.last if rarities is None or row[3] in rarities]
        return items[:limit] if limit else items

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def record_bait(self, name: str) -> None:
        with self._lock:
            self.baits_used[name] += 1

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
