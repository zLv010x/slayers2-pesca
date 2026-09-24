"""Exceções que mudam o rumo da pesca (ficam fora do cycle.py para o relog_bridge usar)."""


class StopRun(Exception):
    """Pedido de parada (F1) ou problema que exige parar a macro."""


class Relogged(Exception):
    """O jogo caiu e a macro reconectou sozinha: recomeça o ciclo do zero."""
