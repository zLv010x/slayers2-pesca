"""Detecção das telas de reconexão (classify) contra prints reais do jogo."""
import cv2
import pytest

import relog
from relog import Screen, classify

# Mesma lista de "jogo normal" do test_menu.py + as fixturas extras de pesca:
# nenhuma pode ser confundida com uma tela de relog.
NEGATIVAS = [
    "idle_com_vara.webp", "idle_sem_vara.webp", "grama_com_vara.webp", "grama_sem_vara.webp",
    "menu_inventario_fishing.webp", "menu_1920x991_fishing.webp", "menu_aberto_333.webp",
    "menu_busca_sem_enter.webp", "minigame_55.webp", "prompt_golden_fish.webp",
    "inventario_raridades.webp", "popup_coral.webp", "popup_golden_fish.webp", "popup_janela_1002.webp",
    "video_aviso_circulo.webp", "video_aviso_losango.webp", "video_brilho_coleta.webp",
    "video_depois_coleta.webp", "video_losango_na_vara_1.webp", "video_losango_na_vara_2.webp",
    "video_losango_na_vara_3.webp",
]


def test_imagem_vazia_nao_quebra():
    assert classify(None).kind == "unknown"


@pytest.mark.parametrize("name", NEGATIVAS)
def test_jogo_normal_nao_e_nenhuma_tela_de_relog(shot, name):
    assert classify(shot(name)).kind == "unknown"


# --- Disconnected -------------------------------------------------------------

@pytest.mark.parametrize("name", ["relog_desconectado_idle_1.webp", "relog_desconectado_idle_2.webp"])
def test_disconnected_e_reconhecido_com_reconnect_leave_e_codigo(shot, name):
    # print de tela inteira (2000x1125, com barra de tarefas): o dialog fica no meio.
    screen = classify(shot(name))
    assert screen.kind == "disconnected"
    assert screen.error_code == 278
    assert screen.message and "idle" in screen.message.lower() and "20" in screen.message
    rx, ry = screen.reconnect_pos
    assert 1030 <= rx <= 1120 and 605 <= ry <= 635
    lx, ly = screen.leave_pos
    assert 890 <= lx <= 970 and 605 <= ly <= 635


@pytest.mark.parametrize("target_h", [720, 640])
def test_disconnected_em_janela_pequena_ainda_acha_o_reconnect(shot, target_h):
    """Na tela inteira o OCR não lê nada nessas resoluções; o recorte ampliado 4x
    (classify) acha o título mesmo torto, e o Reconnect vem pelo fallback de cor
    quando o texto do botão não é lido."""
    img = shot("relog_desconectado_idle_2.webp")
    h, w = img.shape[:2]
    scale = target_h / h
    small = cv2.resize(img, (int(w * scale), target_h), interpolation=cv2.INTER_AREA)
    screen = classify(small)
    assert screen.kind == "disconnected"
    rx, ry = screen.reconnect_pos
    assert abs(rx - 1073 * scale) <= 40
    assert abs(ry - 621 * scale) <= 40


def test_botao_reconnect_por_cor_ignora_forma_que_nao_e_botao(monkeypatch):
    """Sem OCR nenhum pro botão: um quadrado branco maior (não parece botão, aspecto
    baixo) tem que perder pro retângulo branco fino de verdade (aspecto alto)."""
    import numpy as np
    from ocr import Line
    frame = np.zeros((400, 400, 3), dtype="uint8")
    frame[140:200, 150:210] = 255   # quadrado 60x60 (aspecto 1, área maior) — não é botão
    frame[220:240, 140:220] = 255   # retângulo 80x20 (aspecto 4) — o botão de verdade
    lines = [Line("Disconnected", 150, 130, 90, 12)]
    monkeypatch.setattr(relog.ocr, "read_lines", lambda img, min_height=0: lines)
    screen = classify(frame)
    assert screen.kind == "disconnected"
    cx, cy = screen.reconnect_pos
    assert 170 <= cx <= 190 and 220 <= cy <= 240


def test_disconnected_sem_botao_reconnect_fica_com_reconnect_pos_none(monkeypatch):
    """Dialog genérico sem o botão Reconnect (só Leave): a macro não deve reconectar."""
    from ocr import Line
    lines = [Line("Disconnected", 100, 50, 90, 12), Line("Leave", 90, 100, 40, 9)]
    monkeypatch.setattr(relog.ocr, "read_lines", lambda img, min_height=0: lines)
    import numpy as np
    screen = classify(np.zeros((300, 300, 3), dtype="uint8"))
    assert screen.kind == "disconnected"
    assert screen.reconnect_pos is None
    assert screen.leave_pos is not None


def test_relog_result_e_avaliavel_como_bool():
    assert bool(relog.RelogResult(True, "ok")) is True
    assert bool(relog.RelogResult(False, "timeout_total")) is False


def test_codigo_e_lido_mesmo_com_variacao_de_caixa_no_ocr(monkeypatch):
    """"Error Code" às vezes sai com "code" minúsculo: o regex não liga pra caixa."""
    from ocr import Line
    lines = [
        Line("Disconnected", 100, 50, 90, 12),
        Line("(Error code: 264)", 90, 100, 90, 12),
        Line("Reconnect", 140, 130, 55, 9),
    ]
    monkeypatch.setattr(relog.ocr, "read_lines", lambda img, min_height=0: lines)
    import numpy as np
    screen = classify(np.zeros((300, 300, 3), dtype="uint8"))
    assert screen.kind == "disconnected"
    assert screen.error_code == 264


# --- Menu principal -------------------------------------------------------------

def test_menu_principal_e_reconhecido_com_posicao_do_play(shot):
    screen = classify(shot("menu_principal.webp"))
    assert screen.kind == "main_menu"
    px, py = screen.play_pos
    assert 50 <= px <= 160 and 560 <= py <= 640


def test_menu_principal_em_janela_menor_ainda_acha_o_play(shot):
    img = shot("menu_principal.webp")
    small = cv2.resize(img, (1280, 684), interpolation=cv2.INTER_AREA)
    screen = classify(small)
    assert screen.kind == "main_menu"
    assert screen.play_pos is not None


# --- Seleção de servidor --------------------------------------------------------

def test_servidor_lista_acha_o_card_pelo_nome_do_mapa(shot):
    screen = classify(shot("relog_servidor_lista.webp"), {"map_name": "Ouwland"})
    assert screen.kind == "server_select"
    cx, cy = screen.card_pos
    assert 300 <= cx <= 460 and 350 <= cy <= 600


def test_servidor_lista_reduzida_ainda_acha_o_card(shot):
    img = shot("relog_servidor_lista.webp")
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w * 720 / h), 720), interpolation=cv2.INTER_AREA)
    screen = classify(small, {"map_name": "Ouwland"})
    assert screen.kind == "server_select"
    assert screen.card_pos is not None


@pytest.mark.parametrize("name", ["relog_servidor_card_selecionado.webp", "relog_servidor_segurando_join.webp"])
def test_servidor_card_acha_join_e_campo_do_dono(shot, name):
    # "Private server owner" o OCR lê embaralhado nessas duas fixtures (ex.: "Vhivale
    # seive["); por isso owner_field_pos vem por deslocamento a partir do JOIN, não do texto.
    screen = classify(shot(name))
    assert screen.kind == "server_card"
    jx, jy = screen.join_pos
    assert 925 <= jx <= 995 and 910 <= jy <= 945
    ox, oy = screen.owner_field_pos
    assert 880 <= ox <= 1030 and 845 <= oy <= 905
    # nenhuma das duas tem o botão do modo nick: só a legenda "Hold to join..." (tem "hold").
    assert screen.join_private_pos is None


def test_join_private_e_achado_quando_a_legenda_hold_nao_esta_junto(monkeypatch):
    """Sem fixture real (texto do botão do modo nick ainda não confirmado): confere
    que o padrão "join"+"private" tolerante acha uma linha curta simulada."""
    from ocr import Line
    lines = [
        Line("JOIN", 935, 922, 49, 15),
        Line("Join Private", 900, 850, 90, 14),
    ]
    monkeypatch.setattr(relog.ocr, "read_lines", lambda img, min_height=0: lines)
    import numpy as np
    screen = classify(np.zeros((1004, 1918, 3), dtype="uint8"))
    assert screen.kind == "server_card"
    assert screen.join_private_pos is not None


# --- Carregando -------------------------------------------------------------

def test_carregando_now_entering_e_reconhecido(shot):
    screen = classify(shot("relog_carregando_now_entering.webp"))
    assert screen.kind == "loading"



# ---------------------------------------------------------------- "Skip loading!" (25/09)
def _loading_lines():
    from ocr import Line
    return [Line("Loading 85 / 189 Assets..", 700, 770, 130, 10), Line("Skip loading!", 790, 797, 110, 14)]


def test_tela_de_carregamento_do_jogo_acha_o_skip(monkeypatch):
    """Depois do Reconnect o jogo mostra "Loading N / M Assets" e o botão "Skip loading!"."""
    import numpy as np
    monkeypatch.setattr(relog.ocr, "read_lines", lambda img, min_height=0: _loading_lines())
    screen = classify(np.zeros((900, 1600, 3), dtype="uint8"))
    assert screen.kind == "game_loading"
    cx, cy = screen.skip_pos
    assert 790 <= cx <= 900 and 797 <= cy <= 811


class _Actions:
    def __init__(self):
        self.clicks, self.t = [], 0.0

    def click(self, x, y):
        self.clicks.append((x, y))
        return True

    def status(self, msg):
        pass

    def now(self):
        return self.t


def test_relog_clica_no_skip_sem_repetir_toda_hora():
    r = relog.Relogger({}, _Actions())
    screen = Screen(kind="game_loading", skip_pos=(845, 804))
    for t in (0.0, 1.0, 2.0, 6.0):
        r.actions.t = t
        assert r._step(screen, None) is None  # continua esperando carregar
    assert r.actions.clicks == [(845, 804), (845, 804)]  # de novo só depois do intervalo
