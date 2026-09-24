"""Modo "aparecer no Parsec": a janela da macro e o overlay aparecem nas capturas (Parsec/OBS),
mas a macro nunca pode ler a si mesma como se fosse o jogo."""
import numpy as np
import pytest

import capture_mode
import screen
from window import Rect

GAME = Rect(1000, 500, 200, 100)


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    capture_mode.set_own_windows([])
    monkeypatch.setattr(capture_mode.time, "sleep", lambda s: None)
    yield
    capture_mode.set_own_windows([])


def test_pinta_so_o_pedaco_da_janela_que_cai_no_print():
    img = np.full((100, 200, 3), 200, np.uint8)
    capture_mode.mask(img, GAME, [Rect(1150, 450, 100, 100)])  # sai pela direita e por cima
    assert (img[0:50, 150:200] == 0).all()
    assert (img[50:, :] == 200).all() and (img[:, :150] == 200).all()


def test_janela_fora_do_jogo_nao_mexe_no_print():
    img = np.full((100, 200, 3), 200, np.uint8)
    capture_mode.mask(img, GAME, [Rect(0, 0, 300, 300)])
    assert (img == 200).all()


def test_modo_desligado_nao_apaga_nada(monkeypatch):
    monkeypatch.setattr(capture_mode, "own_rects", lambda: [Rect(1000, 500, 50, 50)])
    img = np.full((100, 200, 3), 200, np.uint8)
    assert (capture_mode.mask_frame(img, GAME) == 200).all()


def test_modo_ligado_apaga_as_janelas_nos_prints_da_macro(monkeypatch):
    capture_mode.set_own_windows([11, 22])
    monkeypatch.setattr(capture_mode, "own_rects", lambda: [Rect(1000, 500, 50, 50)])

    class FakeShot:
        def grab(self, box):
            return np.full((box["height"], box["width"], 4), 200, np.uint8)
    g = screen.Grabber.__new__(screen.Grabber)
    g._sct = FakeShot()
    img = g.grab(GAME)
    assert (img[0:50, 0:50] == 0).all() and (img[60:, 60:] == 200).all()


class FakeWindows:
    """Opacidade e estilo de janelas de mentira (11 = overlay em camadas, 22 = janela da macro)."""
    TRANSPARENT = capture_mode.window.WS_EX_TRANSPARENT
    LAYERED = capture_mode.window.WS_EX_LAYERED

    def __init__(self, monkeypatch):
        self.alpha = {11: 224, 22: 255}
        self.style = {11: self.LAYERED, 22: self.LAYERED}
        monkeypatch.setattr(capture_mode.window, "get_alpha", lambda h: self.alpha[h])
        monkeypatch.setattr(capture_mode.window, "set_alpha", lambda h, a: self.alpha.__setitem__(h, a) or True)
        monkeypatch.setattr(capture_mode.window, "get_exstyle", lambda h: self.style[h])
        monkeypatch.setattr(capture_mode.window, "set_exstyle", lambda h, st: self.style.__setitem__(h, st) or True)

    def clicks_pass(self, h):
        return bool(self.style[h] & self.TRANSPARENT)


def test_escondidas_ficam_transparentes_e_voltam_como_estavam(monkeypatch):
    w = FakeWindows(monkeypatch)
    monkeypatch.setattr(capture_mode, "own_rects", lambda: [Rect(1000, 500, 50, 50)])
    capture_mode.set_own_windows([11, 22])
    img = np.full((100, 200, 3), 200, np.uint8)
    with capture_mode.hidden():
        assert w.alpha == {11: 0, 22: 0}
        assert w.clicks_pass(11) and w.clicks_pass(22)  # o clique no PLAY não pode cair na macro
        with capture_mode.hidden():  # aninhado: continua escondido
            assert w.alpha == {11: 0, 22: 0}
        assert w.alpha == {11: 0, 22: 0}
        # transparentes: o que está atrás (menu principal) aparece, não pinta de preto
        assert (capture_mode.mask_frame(img, GAME) == 200).all()
    assert w.alpha == {11: 224, 22: 255}
    assert not w.clicks_pass(11) and not w.clicks_pass(22)


def test_escondidas_voltam_mesmo_com_erro(monkeypatch):
    w = FakeWindows(monkeypatch)
    capture_mode.set_own_windows([11])
    with pytest.raises(RuntimeError):
        with capture_mode.hidden():
            raise RuntimeError("ocr quebrou")
    assert w.alpha[11] == 224 and not w.clicks_pass(11)


def test_overlay_que_ja_deixava_o_clique_passar_continua_assim(monkeypatch):
    """Pescando, o overlay já é "clique passa": esconder e voltar não pode tirar isso."""
    w = FakeWindows(monkeypatch)
    w.style[11] |= w.TRANSPARENT
    capture_mode.set_own_windows([11])
    with capture_mode.hidden():
        pass
    assert w.clicks_pass(11)


def test_so_apaga_janela_sempre_no_topo(monkeypatch):
    """Revisão de 24/09: janela atrás do Roblox não aparece no print, não pode pintar o jogo."""
    capture_mode.set_own_windows([11, 22])
    monkeypatch.setattr(capture_mode.window, "is_topmost", lambda h: h == 11)
    monkeypatch.setattr(capture_mode.window, "visible_rect", lambda h: Rect(h, h, 5, 5))
    assert capture_mode.own_rects() == [Rect(11, 11, 5, 5)]


def test_sem_modo_ligado_esconder_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(capture_mode.window, "set_alpha", lambda h, a: pytest.fail("não devia mexer"))
    with capture_mode.hidden():
        pass


CFG = {"scan_area": {"x": 0.73, "y": 0.29, "w": 0.04, "h": 0.38}, "cast_point": {"x": 0.55, "y": 0.60}}
SCREEN = Rect(0, 0, 2560, 1400)


def test_janela_no_canto_esquerdo_nao_cobre_nada_importante():
    # posição real da janela do usuário em 24/09 (x 48-534, y 163-962)
    assert capture_mode.covered_areas(Rect(48, 163, 486, 799), SCREEN, CFG) == []


def test_avisa_o_que_a_janela_esta_cobrindo():
    covered = capture_mode.covered_areas(Rect(1300, 300, 700, 800), SCREEN, CFG)
    assert "avisos dos itens" in covered and "barra do minigame" in covered
    assert "hotbar" in capture_mode.covered_areas(Rect(1100, 1300, 300, 100), SCREEN, CFG)
    assert "aviso de coleta (T)" in capture_mode.covered_areas(Rect(1100, 600, 100, 100), SCREEN, CFG)
