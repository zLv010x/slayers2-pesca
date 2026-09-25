"""Teste de sensibilidade da câmera: mede sozinho quantos px arrastar (botão direito)
para cada px que a bússola do topo anda.

Cada PC tem uma sensibilidade de mouse e de câmera do Roblox diferente (num PC precisou
de ~16 px/px; o chute inicial da câmera automática em cycle.py é 3): sem medir, a câmera
automática erra várias vezes até "aprender" sozinha. Este módulo faz esse teste sem
ninguém olhando, com as ações (grab do frame, drift da bússola, arrasto, espera e status)
injetadas para dar para testar sem tela de verdade.

Segue a mesma convenção de sinal da câmera automática em cycle.py: para um arrasto `dx`
(via `right_drag`) que muda o desvio da bússola de `drift_before` para `drift_after`,
`moved = drift_before - drift_after` e o ganho é `dx / moved` (px de arrasto por px de
bússola, sinal incluído — se o sentido do arrasto medido for o oposto do esperado, o
ganho sai negativo sozinho, sem precisar de nenhum caso especial).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

import i18n

# Distância de teste inicial (px) do arrasto de calibração.
INITIAL_DRAG_PX = 200.0
# Nunca testa com um arrasto fora dessa faixa (dobra/reduz dentro dela).
MIN_DRAG_PX = 20.0
MAX_DRAG_PX = 800.0
# Bússola andando menos que isso depois de um arrasto de teste não é confiável: dobra o D.
MIN_MOVED_PX = 4.0
# Espera a câmera assentar depois de cada arrasto antes de ler a bússola de novo.
SETTLE_SEC = 0.15
# Quantas medidas (ida e volta) junta antes de tirar a média.
SAMPLES = 3
# Desiste depois de tantas tentativas (medindo ou perdendo a bússola) sem juntar `SAMPLES`.
MAX_ATTEMPTS = 10
# Medidas que variam mais que essa fração da média entre si não são confiáveis.
CONSISTENCY_REL_TOL = 0.35
# Tolerância padrão para considerar que a câmera voltou à posição original.
DEFAULT_RETURN_TOL_PX = 6
# Tentativas de ajuste fino para voltar a câmera à posição original depois do teste.
RETURN_MAX_TRIES = 4
# Trava de segurança: nunca arrasta mais que isso de uma vez (espelha
# cycle.AUTO_CAMERA_MAX_DRAG_PX; não importamos de lá para não criar import circular).
SAFETY_MAX_DRAG_PX = 1500.0


@dataclass
class CalActions:
    """Ações que o teste precisa, injetadas para dar para testar sem tela de verdade.

    `grab_frame` tira um print (só a imagem, sem retângulo: quem chama já resolveu isso).
    `drift` é o `CompassLock.drift_px` (ou uma bússola de mentira nos testes).
    `right_drag` é o `screen.right_drag` (ou quem gravar as chamadas nos testes).
    `sleep`/`status` são opcionais: sem eles o teste só não espera nem avisa nada.
    """
    grab_frame: Callable[[], np.ndarray]
    drift: Callable[[np.ndarray], "int | None"]
    right_drag: Callable[[int], None]
    sleep: Callable[[float], None] = field(default=lambda seconds: None)
    status: Callable[[str], None] = field(default=lambda msg: None)


@dataclass(frozen=True)
class CameraCalResult:
    """ok=True só quando o ganho foi medido E a câmera voltou à posição original.

    `gain` pode vir preenchido mesmo com ok=False (ex.: mediu certo mas não conseguiu
    voltar a câmera dentro da tolerância): quem chama decide se usa mesmo assim.
    """
    ok: bool
    gain: float | None = None
    reason: str | None = None


def _clamp(dx: float) -> int:
    return int(round(max(-SAFETY_MAX_DRAG_PX, min(SAFETY_MAX_DRAG_PX, dx))))


def _consistent(samples: list[float]) -> bool:
    """As amostras precisam concordar no sinal e ficar perto da média (uma sensibilidade
    não-linear, tipo aceleração de mouse do Windows, faria elas variarem bastante)."""
    if any(s == 0 for s in samples):
        return False
    if len({s > 0 for s in samples}) > 1:
        return False
    mean = statistics.mean(samples)
    tol = CONSISTENCY_REL_TOL * abs(mean)
    return all(abs(s - mean) <= tol for s in samples)


def _return_to_drift(actions: CalActions, target: float, current: float, gain: float,
                      tol_px: float) -> tuple[bool, float]:
    """Arrasta de volta até o desvio ficar em `target` (± tol_px), usando o ganho medido."""
    drift = current
    for _ in range(RETURN_MAX_TRIES):
        error = drift - target
        if abs(error) <= tol_px:
            return True, drift
        dx = _clamp(error * gain)
        if dx == 0:
            return abs(error) <= tol_px, drift
        actions.right_drag(dx)
        actions.sleep(SETTLE_SEC)
        new_drift = actions.drift(actions.grab_frame())
        if new_drift is None:
            return False, drift  # perdeu a bússola tentando voltar: não força mais nada
        drift = float(new_drift)
    return abs(drift - target) <= tol_px, drift


def measure_camera_gain(actions: CalActions, tol_px: float = DEFAULT_RETURN_TOL_PX) -> CameraCalResult:
    """Mede o ganho (px de arrasto por px de bússola) arrastando a câmera de teste.

    Precisa do ponto de lançamento e da bússola já marcados (senão `drift` some e a
    função devolve falha na hora, sem mexer em nada). Sempre tenta devolver a câmera
    para onde estava antes de sair, mesmo quando a medição falha.
    """
    frame = actions.grab_frame()
    drift0 = actions.drift(frame)
    if drift0 is None:
        return CameraCalResult(False, None, i18n._(
            "bússola não encontrada: marque o ponto de lançamento (ela precisa estar visível)"))
    actions.status(i18n._("Testando a sensibilidade da câmera..."))
    samples: list[float] = []
    drift = float(drift0)
    direction, d, attempts = 1, INITIAL_DRAG_PX, 0
    while len(samples) < SAMPLES and attempts < MAX_ATTEMPTS:
        attempts += 1
        dx = _clamp(direction * d)
        actions.right_drag(dx)
        actions.sleep(SETTLE_SEC)
        new_drift = actions.drift(actions.grab_frame())
        if new_drift is None:
            # arrastou demais e perdeu a bússola: desfaz e tenta de novo com menos px.
            actions.right_drag(-dx)
            actions.sleep(SETTLE_SEC)
            d = max(MIN_DRAG_PX, d / 2)
            continue
        moved = drift - new_drift
        drift = float(new_drift)
        if abs(moved) < MIN_MOVED_PX:
            d = min(MAX_DRAG_PX, d * 2)  # quase não andou: da próxima vez arrasta mais
            continue
        samples.append(dx / moved)
        direction *= -1  # ida e volta: a próxima amostra desfaz o desvio desta
    if not samples:
        return CameraCalResult(False, None, i18n._(
            "não consegui medir: a câmera não respondeu ao arrasto de teste"))
    if not _consistent(samples):
        return CameraCalResult(False, None, i18n._(
            "medidas inconsistentes: sensibilidade não confiável"))
    gain = statistics.mean(samples)
    returned, drift = _return_to_drift(actions, drift0, drift, gain, tol_px)
    if not returned:
        return CameraCalResult(False, gain, i18n._(
            "câmera não voltou à posição original depois do teste"))
    return CameraCalResult(True, gain, None)
