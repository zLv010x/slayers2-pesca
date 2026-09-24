"""Quantos reinícios automáticos da pesca cabem numa hora.

Fica só com a contagem (sem tocar no Tk nem no config): o app.py lê o limite
configurado na aba Avançado a cada parada e pergunta a este objeto se ainda
pode tentar de novo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

HOUR_SEC = 3600.0


@dataclass
class RestartPolicy:
    now: Callable[[], float] = time.monotonic
    _restarts: list[float] = field(default_factory=list)

    def _recent(self) -> list[float]:
        cutoff = self.now() - HOUR_SEC
        self._restarts = [t for t in self._restarts if t >= cutoff]
        return self._restarts

    def allowed(self, max_per_hour: int) -> bool:
        """Ainda dá para tentar reiniciar sozinha sem passar do teto da última hora?"""
        return len(self._recent()) < max_per_hour

    def record_restart(self) -> None:
        self._restarts.append(self.now())
