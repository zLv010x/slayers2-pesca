"""Controle das iscas: quantas tem, quanto tempo duram e qual usar quando uma acabar.

Regras do jogo (texto das próprias iscas):
- Worm (common) e Fish Head (rare) gastam 1 a cada mordida resolvida (pegando ou não);
- Drowned Lure (legendary) não gasta.
Então a macro desconta 1 a cada minigame jogado da isca equipada.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from session import format_elapsed

# Média móvel do tempo de um ciclo (pesos: 90% histórico, 10% novo).
AVG_WEIGHT = 0.1
# Contagem que não deu para ler: confere de novo depois de tantos minigames.
UNKNOWN_RECHECK_EVERY = 100


@dataclass
class BaitState:
    counts: dict[str, int | None] = field(default_factory=dict)  # None = tem, mas sem número
    owned: list[str] = field(default_factory=list)
    equipped: str | None = None
    checked_at: str | None = None
    avg_cycle_sec: float = 0.0
    since_check: int = 0          # minigames desde a última conferida no inventário
    left_at_check: int | None = None  # quantas tinha na última conferida

    # ------------------------------------------------------------ disco
    @classmethod
    def load(cls, path: Path) -> "BaitState":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    @property
    def checked(self) -> bool:
        return self.checked_at is not None

    # ------------------------------------------------------------ uso
    def remaining(self) -> int | None:
        if self.equipped is None:
            return None
        return self.counts.get(self.equipped)

    def is_infinite(self, infinite: list[str]) -> bool:
        return self.equipped in infinite

    def consume(self, cycle_sec: float, infinite: list[str]) -> None:
        """Um minigame foi jogado: gasta 1 da isca equipada (se ela gasta)."""
        if cycle_sec > 0:
            self.avg_cycle_sec = (cycle_sec if self.avg_cycle_sec <= 0
                                  else (1 - AVG_WEIGHT) * self.avg_cycle_sec + AVG_WEIGHT * cycle_sec)
        self.since_check += 1
        left = self.remaining()
        if self.equipped and self.equipped not in infinite and left is not None:
            self.counts[self.equipped] = max(0, left - 1)

    def eta_seconds(self, infinite: list[str]) -> float | None:
        left = self.remaining()
        if self.is_infinite(infinite) or left is None or self.avg_cycle_sec <= 0:
            return None
        return left * self.avg_cycle_sec

    def summary(self, infinite: list[str]) -> str:
        if not self.checked:
            return "Iscas: ainda não conferidas"
        if self.equipped is None:
            return "Sem isca equipada"
        if self.is_infinite(infinite):
            return f"Isca: {self.equipped} (não gasta)"
        left = self.remaining()
        if left is None:
            return f"Isca: {self.equipped} (quantidade ?)"
        eta = self.eta_seconds(infinite)
        return f"Isca: {self.equipped} · {left}" + (f" · ~{format_elapsed(eta)}" if eta else "")

    def needs_check(self, recheck_at: int, infinite: list[str]) -> bool:
        """Hora de abrir o inventário para conferir de verdade?"""
        if not self.checked:
            return True
        if self.equipped is None or self.is_infinite(infinite):
            return False
        left = self.remaining()
        if left is None:
            return self.since_check >= UNKNOWN_RECHECK_EVERY
        if self.left_at_check == 0:
            return False  # já conferiu que acabou e não tinha outra: não fica abrindo o menu à toa
        # já estava perto do fim na última conferida: só confere de novo quando a conta zerar
        limit = recheck_at if self.left_at_check is None or self.left_at_check > recheck_at else 0
        return left <= limit

    def usable(self, name: str, infinite: list[str]) -> bool:
        if name not in self.owned:
            return False
        count = self.counts.get(name)
        return name in infinite or count is None or count > 0

    def choose(self, order: list[str], infinite: list[str]) -> str | None:
        """Melhor isca que ainda dá para usar, na ordem de preferência."""
        return next((name for name in order if self.usable(name, infinite)), None)

    def mark_checked(self) -> None:
        self.checked_at = datetime.now().isoformat(timespec="seconds")
        self.since_check = 0
        self.left_at_check = self.remaining()

    @property
    def warning(self) -> bool:
        return self.checked and (self.equipped is None or self.remaining() == 0)
