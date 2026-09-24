from restart_policy import RestartPolicy


def test_permite_ate_o_limite_por_hora():
    now = [0.0]
    p = RestartPolicy(now=lambda: now[0])
    assert p.allowed(3)
    p.record_restart()
    assert p.allowed(3)
    p.record_restart()
    assert p.allowed(3)
    p.record_restart()
    assert not p.allowed(3)


def test_reinicio_antigo_sai_da_conta_depois_de_uma_hora():
    now = [0.0]
    p = RestartPolicy(now=lambda: now[0])
    for _ in range(3):
        p.record_restart()
    assert not p.allowed(3)
    now[0] = 3601.0  # mais de uma hora depois: os reinícios antigos não contam mais
    assert p.allowed(3)


def test_zero_por_hora_nunca_permite():
    p = RestartPolicy(now=lambda: 0.0)
    assert not p.allowed(0)


def test_sem_reinicios_ainda_comeca_zerado():
    p = RestartPolicy(now=lambda: 100.0)
    assert p.allowed(1)
