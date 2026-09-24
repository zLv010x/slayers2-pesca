from baits import BaitState

ORDER = ["Fish Head", "Drowned Lure", "Worm"]
INF = ["Drowned Lure"]


def _state(**counts):
    names = {"fish": "Fish Head", "lure": "Drowned Lure", "worm": "Worm"}
    s = BaitState(counts={names[k]: v for k, v in counts.items()}, owned=[names[k] for k in counts])
    s.mark_checked()
    return s


def test_gasta_uma_por_minigame_e_estima_o_tempo():
    s = _state(fish=100, lure=None)
    s.equipped = "Fish Head"
    for _ in range(10):
        s.consume(12.0, INF)
    assert s.remaining() == 90
    assert s.eta_seconds(INF) == 90 * 12.0
    assert s.summary(INF) == "Isca: Fish Head · 90 · ~18m 00s"


def test_lendaria_nao_gasta():
    s = _state(lure=None)
    s.equipped = "Drowned Lure"
    s.consume(12.0, INF)
    assert s.summary(INF) == "Isca: Drowned Lure (não gasta)"
    assert not s.needs_check(10, INF)


def test_confere_quando_esta_perto_de_acabar():
    s = _state(fish=12)
    s.equipped = "Fish Head"
    assert not s.needs_check(10, INF)
    s.consume(10, INF)
    s.consume(10, INF)
    assert s.needs_check(10, INF)


def test_primeira_vez_precisa_conferir():
    assert BaitState().needs_check(10, INF)


def test_troca_rare_por_lendaria_e_depois_por_comum():
    s = _state(fish=0, lure=None, worm=13)
    assert s.choose(ORDER, INF) == "Drowned Lure"
    amigo = _state(fish=0, worm=13)            # sem a lendária
    assert amigo.choose(ORDER, INF) == "Worm"
    sem_nada = _state(fish=0, worm=0)
    assert sem_nada.choose(ORDER, INF) is None


def test_salva_e_carrega(tmp_path):
    s = _state(fish=662, lure=None)
    s.equipped = "Fish Head"
    s.save(tmp_path / "iscas.json")
    back = BaitState.load(tmp_path / "iscas.json")
    assert back.remaining() == 662 and back.checked
    assert BaitState.load(tmp_path / "nao_existe.json").checked is False


def test_perto_do_fim_nao_fica_abrindo_o_menu_toda_hora():
    s = _state(fish=8)
    s.equipped = "Fish Head"
    s.mark_checked()                  # conferiu: 8 de verdade
    s.consume(10, INF)
    assert not s.needs_check(10, INF)  # só confere de novo quando a conta chegar a 0
    for _ in range(7):
        s.consume(10, INF)
    assert s.needs_check(10, INF)
    s.mark_checked()                  # conferiu: acabou mesmo e não tinha outra
    assert not s.needs_check(10, INF)
