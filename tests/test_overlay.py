from collections import Counter

import overlay
from window import Rect

ZONE = {"x0": 0.0, "x1": 0.14, "y0": 0.40, "y1": 0.60}


def test_fish_by_name_and_known_list():
    assert overlay.kind_of("Zebra Fish") == "peixe"
    assert overlay.kind_of("OuwFish") == "peixe"
    assert overlay.kind_of("Krathulon") == "peixe"
    assert overlay.kind_of("crustadon") == "peixe"
    assert overlay.kind_of("Sea Horse") == "peixe"


def test_everything_else_is_item():
    for name in ("Squid Beanie", "Refinement Ore", "Metal Scraps", "Lost Mask"):
        assert overlay.kind_of(name) == "item", name


def test_split_sorts_by_quantity_then_name():
    counts = Counter({"Ore": 3, "Clown Fish": 5, "Golden Fish": 5, "Coral": 7, "Zebra Fish": 1})
    fish, items = overlay.split_counts(counts)
    assert fish == [("Clown Fish", 5), ("Golden Fish", 5), ("Zebra Fish", 1)]
    assert items == [("Ore", 3)]


def test_split_ignores_zero_and_blank():
    fish, items = overlay.split_counts(Counter({"": 2, "Coral": 0, "Ore": 1}))
    assert fish == []
    assert items == [("Ore", 1)]


def test_trim_keeps_top_rows_and_counts_the_rest():
    rows = [(f"Item {i}", 10 - i) for i in range(10)]
    shown, rest = overlay.trim(rows, 4)
    assert shown == rows[:4]
    assert rest == 6
    assert overlay.trim(rows[:3], 4) == (rows[:3], 0)


def test_default_position_is_over_party_zone():
    pos = overlay.default_pos(ZONE)
    assert ZONE["x0"] <= pos["x"] < ZONE["x1"]
    assert ZONE["y0"] <= pos["y"] < ZONE["y1"]


def test_screen_round_trip_follows_window():
    pos = {"x": 0.01, "y": 0.42}
    r = Rect(100, 50, 1000, 800)
    x, y = overlay.to_screen(r, pos)
    assert (x, y) == (110, 386)
    assert overlay.from_screen(r, x, y) == {"x": 0.01, "y": 0.42}
    bigger = Rect(0, 0, 2000, 1000)
    assert overlay.to_screen(bigger, pos) == (20, 420)


def test_from_screen_clamps_inside_window():
    r = Rect(0, 0, 1000, 1000)
    assert overlay.from_screen(r, -300, 5000) == {"x": 0.0, "y": overlay.MAX_FRAC}


def test_valid_pos_rejects_garbage():
    assert overlay.valid_pos({"x": 0.2, "y": 0.5}) == {"x": 0.2, "y": 0.5}
    assert overlay.valid_pos({"x": 2, "y": 0.5}) is None
    assert overlay.valid_pos({"x": "a", "y": 0.5}) is None
    assert overlay.valid_pos({"x": True, "y": 0.5}) is None
    assert overlay.valid_pos(None) is None
    assert overlay.valid_pos([0.1, 0.2]) is None


def flat(lines):
    return [f"{ln.text}  {ln.qty}" if ln.qty is not None else ln.text for ln in lines]


def test_lines_show_time_sections_and_baits():
    lines = overlay.build_lines(
        "1h 02m 03s",
        Counter({"Clown Fish": 2, "Ore": 5}),
        Counter({"Fish Head": 7}),
        max_rows=8,
    )
    texts = flat(lines)
    assert texts[0] == "⏱ 1h 02m 03s"
    assert "Peixes (2)" in texts and "Clown Fish  2" in texts
    assert "Itens (5)" in texts and "Ore  5" in texts
    assert "Iscas gastas (7)" in texts and "Fish Head  7" in texts


def test_lines_empty_session_says_nothing_yet():
    assert flat(overlay.build_lines("0m 00s", Counter(), Counter(), max_rows=8)) == ["⏱ 0m 00s", "Nada pego ainda"]


def test_lines_baits_without_catch():
    texts = flat(overlay.build_lines("0m 30s", Counter(), Counter({"Worm": 2}), max_rows=8))
    assert texts == ["⏱ 0m 30s", "Nada pego ainda", "Iscas gastas (2)", "Worm  2"]


def test_lines_overflow_row():
    counts = Counter({f"Fish {i}": 1 for i in range(5)})
    assert "+2 outros" in flat(overlay.build_lines("0m 01s", counts, Counter(), max_rows=3))


# ---------------------------------------------------------------- valor dos peixes (24/09)
PRICES = {"Zebra Fish": 66, "Clown Fish": 40}


def test_cada_peixe_mostra_o_valor_se_vender_todos():
    lines = overlay.build_lines("1m 00s", Counter({"Zebra Fish": 295, "Clown Fish": 3}), Counter(),
                                max_rows=8, prices=PRICES)
    rows = {ln.text: ln for ln in lines if ln.style == "row"}
    assert rows["Zebra Fish"].value == 295 * 66 and rows["Clown Fish"].value == 120


def test_total_de_todos_os_peixes_embaixo_da_lista():
    counts = Counter({"Zebra Fish": 2, "Clown Fish": 1, "Golden Fish": 5, "Ore": 3})
    lines = overlay.build_lines("1m 00s", counts, Counter(), max_rows=1, prices=PRICES)
    total = [ln for ln in lines if ln.style == "total"]
    assert len(total) == 1 and total[0].value == 2 * 66 + 40  # conta até os que ficaram em "+N outros"
    styles = [ln.style for ln in lines]
    assert styles.index("total") < styles.index("head", styles.index("total"))  # antes da seção Itens


def test_peixe_sem_preco_fica_sem_valor_e_sem_total():
    lines = overlay.build_lines("1m 00s", Counter({"Golden Fish": 5}), Counter(), max_rows=8, prices=PRICES)
    assert all(ln.value is None for ln in lines) and "total" not in [ln.style for ln in lines]


def test_formata_valor_com_ponto_de_milhar():
    assert overlay.money(19470) == "19.470" and overlay.money(66) == "66"


def test_coral_conta_como_peixe_e_entra_no_total():
    """Pedido de 24/09: só peixe tem preço de venda, e o Coral conta como peixe."""
    assert overlay.kind_of("Coral") == "peixe"
    lines = overlay.build_lines("1m 00s", Counter({"Coral": 3, "Zebra Fish": 1, "Ore": 2}), Counter(),
                                prices={"Coral": 33, "Zebra Fish": 66})
    assert next(ln for ln in lines if ln.style == "total").value == 3 * 33 + 66
