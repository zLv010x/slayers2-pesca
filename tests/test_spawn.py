"""Setar o spawn pelo gamepass: Commands -> caixinha "command" -> lista aberta ->
digita "set" -> Enter -> ✓ verde. Nunca digita sem ver a lista aberta (o "S" andaria
com o personagem para trás, tirando ele do ponto de pesca)."""
import numpy as np
import pytest

import spawn
from spawn import Setter, SpawnScreen

FIXTURES = {
    "normal": "spawn_commands_botao.png",
    "closed_box": "spawn_command_caixa.png",
    "list_open": "spawn_command_lista.png",
    "confirm": "spawn_set_confirmar.png",
}


def _frame_with(shot, name, size=(1920, 1080), crop=None):
    """Print do botão colado onde ele fica no jogo (alto, ~13% da largura) numa tela escura."""
    w, h = size
    frame = np.full((h, w, 3), (90, 70, 40), np.uint8)
    crop = shot(name) if crop is None else crop
    ch, cw = crop.shape[:2]
    x0, y0 = int(0.10 * w), int(0.015 * h)
    frame[y0:y0 + ch, x0:x0 + cw] = crop
    return frame, (x0, y0)


@pytest.mark.parametrize("kind", list(FIXTURES))
def test_reconhece_cada_estado(shot, kind, real_classify):
    frame, _ = _frame_with(shot, FIXTURES[kind])
    assert real_classify(frame).kind == kind


def test_posicoes_caem_dentro_dos_botoes(shot, real_classify):
    frame, _ = _frame_with(shot, FIXTURES["confirm"])
    s = real_classify(frame)
    cx, cy = s.confirm_pos
    b, g, r = (int(v) for v in frame[cy, cx])
    assert g > r and g > b                   # verde de verdade embaixo do ponto
    xx, xy = s.cancel_pos
    assert xx < cx and abs(xy - cy) < 15     # X à esquerda, na mesma linha


def test_tela_de_jogo_acha_o_botao_commands_no_alto(shot, real_classify):
    """Revisão de 24/09: o botão fica no alto à ESQUERDA (~13%), não no canto direito."""
    img = shot("idle_com_vara.webp")
    s = real_classify(img)
    assert s.kind == "normal"
    h, w = img.shape[:2]
    assert abs(s.commands_pos[0] / w - 0.135) < 0.03 and s.commands_pos[1] / h < 0.08


def test_tela_sem_o_botao_e_unknown(shot, real_classify):
    assert real_classify(shot("menu_1920x991_fishing.webp")).kind == "unknown"


def test_palavras_soltas_longe_nao_abrem_a_lista(shot, real_classify):
    """Revisão de 24/09: "PVP"/"Mod"/"Ban" soltos na tela (party, HUD) não podem valer como a
    lista aberta — senão digitaria "set" com a caixinha fechada."""
    import cv2
    frame, (x0, y0) = _frame_with(shot, FIXTURES["closed_box"])
    for i, word in enumerate(("Ban", "Mod", "PVP")):
        cv2.putText(frame, word, (x0 + 700, y0 + 150 + 40 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    assert real_classify(frame).kind == "closed_box"


def test_imagem_vazia(real_classify):
    assert real_classify(None).kind == "unknown"


# ---------------------------------------------------------------- máquina de estados

POS = {"commands": (1800, 70), "pill": (1780, 70), "cancel": (1740, 70), "confirm": (1830, 70)}
SCREENS = {
    "normal": SpawnScreen("normal", commands_pos=POS["commands"]),
    "closed_box": SpawnScreen("closed_box", pill_pos=POS["pill"], cancel_pos=POS["cancel"]),
    "list_open": SpawnScreen("list_open", pill_pos=POS["pill"], cancel_pos=POS["cancel"]),
    "typed": SpawnScreen("typed", pill_pos=POS["pill"], cancel_pos=POS["cancel"]),
    "confirm": SpawnScreen("confirm", pill_pos=POS["pill"], cancel_pos=POS["cancel"],
                           confirm_pos=POS["confirm"]),
    "unknown": SpawnScreen("unknown"),
}


class FakeGame:
    """Jogo de mentira: cada ação muda a tela como no jogo de verdade."""

    def __init__(self, focus_works=True):
        self.kind = "normal"
        self.t = 0.0
        self.log = []
        self.focus_works = focus_works

    def grab(self):
        return 0, 0, self.kind

    def click(self, x, y):
        self.log.append(("click", (x, y)))
        pos = (x, y)
        if self.kind == "normal" and pos == POS["commands"]:
            self.kind = "closed_box"
        elif self.kind == "closed_box" and pos == POS["pill"]:
            self.kind = "list_open" if self.focus_works else "closed_box"
        elif self.kind == "confirm" and pos == POS["confirm"]:
            self.kind = "normal"
        elif pos == POS["cancel"]:
            self.kind = "normal"

    def type_text(self, text):
        self.log.append(("type", text))
        if self.kind == "list_open" and text == "set":
            self.kind = "typed"

    def press(self, key):
        self.log.append(("press", key))
        if self.kind == "typed" and key == "enter":
            self.kind = "confirm"

    def sleep(self, sec):
        self.t += sec

    def now(self):
        return self.t

    def status(self, msg):
        pass


@pytest.fixture
def real_classify():
    return spawn.classify


@pytest.fixture
def fake_screens(monkeypatch):
    monkeypatch.setattr(spawn, "classify", lambda frame: SCREENS.get(frame, SCREENS["unknown"]))


def test_fluxo_completo_seta_o_spawn(fake_screens):
    game = FakeGame()
    result = Setter(game).run()
    assert result.ok
    assert game.log == [("click", POS["commands"]), ("click", POS["pill"]), ("type", "set"),
                        ("press", "enter"), ("click", POS["confirm"])]


def test_nunca_digita_sem_a_lista_aberta(fake_screens):
    """Clicou na caixinha mas ela não abriu: não pode digitar (as letras iriam para o jogo)."""
    game = FakeGame(focus_works=False)
    result = Setter(game).run()
    assert not result.ok
    assert not any(kind == "type" for kind, _ in game.log)
    assert game.log[-1] == ("click", POS["cancel"])  # fecha a caixinha ao desistir
    assert game.kind == "normal"


def test_digitou_mas_nao_apareceu_set_cancela_sem_enter(fake_screens):
    class TypingFails(FakeGame):
        def type_text(self, text):
            self.log.append(("type", text))  # o texto não entrou na caixinha
    game = TypingFails()
    result = Setter(game).run()
    assert not result.ok
    assert ("press", "enter") not in game.log
    assert game.log.count(("type", "set")) == 1  # nunca digita de novo em cima
    assert game.log[-1] == ("click", POS["cancel"])


def test_lista_ja_aberta_sem_eu_abrir_nao_digita(fake_screens):
    game = FakeGame()
    game.kind = "list_open"
    result = Setter(game).run()
    assert not result.ok
    assert not any(kind == "type" for kind, _ in game.log)
    assert game.log[-1] == ("click", POS["cancel"])


def test_leitura_atrasada_nao_digita(fake_screens):
    """Roblox saiu da frente entre duas leituras: a caixinha pode ter perdido o foco."""
    class SlowReads(FakeGame):
        def grab(self):
            self.t += 2.0
            return super().grab()
    game = SlowReads()
    result = Setter(game).run()
    assert not result.ok
    assert not any(kind == "type" for kind, _ in game.log)


def test_desiste_sem_clicar_onde_o_x_estava(fake_screens):
    """Revisão de 24/09: ao desistir, só clica no X se ele estiver na tela agora."""
    class Vanishes(FakeGame):
        def click(self, x, y):
            super().click(x, y)
            if self.kind == "closed_box":
                self.kind = "sumiu"  # tela que o classify não reconhece
    game = Vanishes()
    result = Setter(game).run()
    assert not result.ok
    assert ("click", POS["cancel"]) not in game.log


def test_check_clicado_e_caixinha_sumiu_conta_como_setado(fake_screens):
    class ConfirmVanishes(FakeGame):
        def click(self, x, y):
            super().click(x, y)
            if (x, y) == POS["confirm"]:
                self.kind = "sumiu"
    result = Setter(ConfirmVanishes()).run()
    assert result.ok


def test_clique_no_check_que_nao_saiu_nao_conta(fake_screens):
    class MouseBusy(FakeGame):
        def click(self, x, y):
            if (x, y) == POS["confirm"]:
                self.log.append(("click-falhou", (x, y)))
                return False
            super().click(x, y)
    result = Setter(MouseBusy()).run()
    assert not result.ok


def test_sem_botao_commands_desiste_sem_fazer_nada(fake_screens):
    game = FakeGame()
    game.kind = "unknown"
    result = Setter(game).run()
    assert not result.ok and game.log == []


@pytest.mark.parametrize("kind", list(FIXTURES))
def test_reconhece_cada_estado_com_a_interface_menor(shot, kind, real_classify):
    """Janela menor (amigos) = botões menores."""
    import cv2
    small = cv2.resize(shot(FIXTURES[kind]), None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA)
    frame, _ = _frame_with(shot, FIXTURES[kind], crop=small)
    assert real_classify(frame).kind == kind


def test_nao_clica_no_check_sem_ter_digitado(fake_screens):
    """Um ✓ verde que aparece sozinho (outra coisa do jogo) não pode ser clicado."""
    game = FakeGame()
    game.kind = "confirm"
    result = Setter(game).run()
    assert not result.ok
    assert ("click", POS["confirm"]) not in game.log
