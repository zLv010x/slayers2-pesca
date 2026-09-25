"""Teste de sensibilidade da câmera (camera_cal.py) com uma bússola de mentira: ela anda
`dx * real_gain` px (com ruído opcional) a cada `right_drag(dx)`, e "some" (drift vira
None) além de um alcance de rastreio — como o casamento de template de verdade quando a
câmera girou demais. O código testado nunca vê `real_gain`: só descobre pela resposta,
exatamente como a câmera automática de cycle.py."""
import pytest

import camera_cal


class FakeCameraCal:
    def __init__(self, drift0=0.0, real_gain=1 / 3, track_limit=100_000.0, noise=0.0,
                 dead=False, break_after_drags=None):
        self.pos = float(drift0)
        self.real_gain = real_gain
        self.track_limit = track_limit
        self.noise = noise      # ruído (fração) alternado a cada arrasto: resposta não-linear
        self.dead = dead        # a câmera nunca responde (ex.: Roblox fora de foco)
        self.break_after_drags = break_after_drags  # bússola some de vez após tantos arrastos
        self.drags: list[int] = []
        self._n = 0

    def right_drag(self, dx: int) -> None:
        self.drags.append(dx)
        self._n += 1
        if self.dead:
            return
        factor = 1.0 + (self.noise if self._n % 2 else -self.noise)
        self.pos -= dx * self.real_gain * factor

    def drift(self, frame):
        if self.break_after_drags is not None and self._n > self.break_after_drags:
            return None
        if abs(self.pos) > self.track_limit:
            return None
        return int(round(self.pos))

    def grab_frame(self):
        return None  # o conteúdo do frame não importa: só a bússola de mentira olha a "posição"

    def actions(self, status_log=None) -> camera_cal.CalActions:
        return camera_cal.CalActions(
            grab_frame=self.grab_frame, drift=self.drift, right_drag=self.right_drag,
            sleep=lambda s: None,
            status=(status_log.append if status_log is not None else (lambda m: None)))


# ---------------------------------------------------------------- medir ganhos diferentes

@pytest.mark.parametrize("real_gain, expected_gain", [
    (1 / 3, 3.0),
    (1 / 16, 16.0),   # como o Ewerton: precisou de ~16 px/px
    (1 / 40, 40.0),
    (-1 / 10, -10.0),  # sentido invertido: ganho sai negativo sozinho
])
def test_mede_o_ganho_real_com_sinal(real_gain, expected_gain):
    compass = FakeCameraCal(drift0=0.0, real_gain=real_gain)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is True
    # a bússola de verdade só devolve px inteiros: arredondar introduz um pouco de viés
    # (aqui até uns 5%), por isso a tolerância — não é exatidão de ponto flutuante.
    assert result.gain == pytest.approx(expected_gain, rel=0.05)


def test_status_avisa_que_esta_testando():
    compass = FakeCameraCal(drift0=10.0, real_gain=1 / 3)
    log = []
    camera_cal.measure_camera_gain(compass.actions(status_log=log))
    assert any("sensibilidade" in msg.lower() for msg in log)


# ---------------------------------------------------------------- dobra o D

def test_dobra_o_arrasto_de_teste_quando_a_bussola_quase_nao_anda():
    """real_gain bem pequeno: o arrasto inicial (200px) move a bússola menos que o mínimo
    confiável (4px), então o próximo arrasto de teste tem que ser maior."""
    compass = FakeCameraCal(drift0=0.0, real_gain=0.01)  # 200*0.01 = 2px: quase não anda
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is True
    assert result.gain == pytest.approx(100.0, rel=0.02)
    assert compass.drags[0] == pytest.approx(200, abs=1)
    assert abs(compass.drags[1]) > abs(compass.drags[0])  # dobrou depois de quase não andar


# ---------------------------------------------------------------- bússola sumindo

def test_reduz_o_arrasto_e_desfaz_quando_a_bussola_some():
    """real_gain bem alto: o arrasto inicial (200px) faz a bússola sumir (passa do alcance
    de rastreio); o teste tem que desfazer esse arrasto e tentar de novo com menos px."""
    compass = FakeCameraCal(drift0=0.0, real_gain=5.0, track_limit=150.0)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is True
    assert result.gain == pytest.approx(0.2, rel=0.02)
    # os 3 primeiros arrastos (200, 100, 50) sumiram com a bússola e foram desfeitos
    # (arrasto seguido do oposto exato), cada vez com menos px que o anterior
    reverts = list(zip(compass.drags[0:6:2], compass.drags[1:6:2]))
    for dx, undo in reverts:
        assert undo == -dx
    assert abs(compass.drags[0]) > abs(compass.drags[2]) > abs(compass.drags[4])
    assert abs(compass.pos) <= camera_cal.DEFAULT_RETURN_TOL_PX  # voltou para onde estava


# ---------------------------------------------------------------- sempre volta a câmera

@pytest.mark.parametrize("drift0, real_gain", [
    (0.0, 1 / 3), (5.0, 1 / 3), (0.0, 1 / 16), (-30.0, -1 / 8),
])
def test_sempre_volta_a_camera_para_o_drift_inicial(drift0, real_gain):
    compass = FakeCameraCal(drift0=drift0, real_gain=real_gain)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is True
    assert abs(compass.pos - drift0) <= camera_cal.DEFAULT_RETURN_TOL_PX


def test_falha_quando_nao_consegue_voltar_dentro_da_tolerancia():
    """A bússola some de vez logo depois de medir (ex.: a janela mexeu): a medição foi
    boa (`gain` vem preenchido), mas o teste tem que avisar que não voltou."""
    compass = FakeCameraCal(drift0=0.0, real_gain=1 / 3, break_after_drags=3)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is False
    assert result.gain == pytest.approx(3.0, rel=0.02)
    assert "voltou" in result.reason


# ---------------------------------------------------------------- falhas claras

def test_falha_clara_sem_ponto_ou_bussola_marcados():
    """Sem `capture()` nunca ter sido chamado, `compass.drift_px` sempre devolve None: o
    teste precisa recusar na hora, sem arrastar a câmera de jeito nenhum."""
    actions = camera_cal.CalActions(
        grab_frame=lambda: None, drift=lambda frame: None,
        right_drag=lambda dx: pytest.fail("não devia arrastar a câmera sem ponto marcado"),
        sleep=lambda s: None)
    result = camera_cal.measure_camera_gain(actions)
    assert result.ok is False
    assert result.gain is None
    assert "bússola" in result.reason


def test_falha_quando_a_camera_nunca_responde():
    """A câmera não reage a nenhum arrasto (ex.: Roblox sem foco): nunca junta uma
    medida confiável e desiste com um motivo claro, sem girar para sempre."""
    compass = FakeCameraCal(drift0=0.0, dead=True)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is False
    assert result.gain is None
    assert "não respondeu" in result.reason
    assert len(compass.drags) <= camera_cal.MAX_ATTEMPTS


def test_recusa_medidas_inconsistentes():
    """Resposta bem não-linear (ruído grande entre um arrasto e outro, como uma
    aceleração de mouse do Windows malucamente forte): as amostras discordam demais
    entre si e o teste recusa a medir em vez de inventar um ganho."""
    compass = FakeCameraCal(drift0=0.0, real_gain=1 / 3, noise=0.6)
    result = camera_cal.measure_camera_gain(compass.actions())
    assert result.ok is False
    assert result.gain is None
    assert "inconsistentes" in result.reason


def test_nao_arrasta_alem_do_limite_de_seguranca():
    """Mesmo com um ganho medido enorme, a volta final nunca manda um arrasto maluco."""
    compass = FakeCameraCal(drift0=0.0, real_gain=1 / 3)
    camera_cal.measure_camera_gain(compass.actions())
    assert all(abs(dx) <= camera_cal.SAFETY_MAX_DRAG_PX for dx in compass.drags)
