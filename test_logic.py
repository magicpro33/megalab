"""Regression checks for odds, parsing, and pick generation."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from lottery_core import (
    GAMES,
    any_prize_probability,
    digit_box_ways,
    expected_multiplier,
    format_pick_plain,
    generate,
    load_game_history,
    matrix_tier_probability,
    never_drawn_pick,
    parse_digit_row,
    parse_history,
    parse_int_tokens,
)
import pandas as pd

APP_DIR = Path(__file__).resolve().parent


def assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: got {actual}, expected {expected} (±{tol})")


def test_mega_millions_odds() -> None:
    g = GAMES["Mega Millions"]
    official = {
        (5, True): 290_472_336,
        (5, False): 12_629_232,
        (4, True): 893_761.0338,
        (4, False): 38_859.1754,
        (3, True): 13_965.0162,
        (3, False): 607.1746,
        (2, True): 665.0008,
        (1, True): 85.8066,
        (0, True): 35.1666,
    }
    for (km, bm), odds in official.items():
        computed = 1 / matrix_tier_probability(g, km, bm)
        assert_close(computed, odds, 0.05, f"MM {km}+{bm}")
    assert_close(1 / any_prize_probability(g), 23.0737, 0.02, "MM any prize")
    assert_close(expected_multiplier(g["multipliers"]), 3.0, 0.01, "MM E[multiplier]")
    jackpot = 200_000_000
    ev = 0.0
    em = expected_multiplier(g["multipliers"])
    for km, bm, prize, _label in g["tiers"]:
        p = matrix_tier_probability(g, km, bm)
        ev += p * (jackpot if prize is None else prize * em)
    # $5 ticket; EV must stay well below face value at a $200M cash jackpot.
    assert 0.8 < ev < 3.0, f"MM EV out of range: {ev}"


def test_powerball_odds() -> None:
    g = GAMES["Powerball"]
    official = {
        (5, True): 292_201_338.00,
        (5, False): 11_688_053.52,
        (4, True): 913_129.18,
        (4, False): 36_525.17,
        (3, True): 14_494.11,
        (3, False): 579.76,
        (2, True): 701.33,
        (1, True): 91.98,
        (0, True): 38.32,
    }
    for (km, bm), odds in official.items():
        computed = 1 / matrix_tier_probability(g, km, bm)
        assert_close(computed, odds, 0.05, f"PB {km}+{bm}")
    assert_close(1 / any_prize_probability(g), 24.87, 0.02, "PB any prize")


def test_palmetto_odds_and_price() -> None:
    g = GAMES["Palmetto Cash 5"]
    assert g["price"] == 2.0
    assert g["tiers"][2][2] == 5  # Match 3 base prize
    assert math.comb(42, 5) == 850_668
    assert_close(1 / matrix_tier_probability(g, 5, None), 850_668, 0.5, "PC5 jackpot")
    assert_close(1 / matrix_tier_probability(g, 4, None), 4_598.2, 0.5, "PC5 match 4")
    assert_close(1 / matrix_tier_probability(g, 3, None), 127.73, 0.5, "PC5 match 3")
    assert_close(1 / matrix_tier_probability(g, 2, None), 10.95, 0.05, "PC5 match 2")
    assert_close(1 / any_prize_probability(g), 10.0, 0.15, "PC5 any prize")
    assert expected_multiplier(g["multipliers"]) > 4.0


def test_digit_box_ways() -> None:
    assert digit_box_ways([1, 2, 3, 4]) == 24
    assert digit_box_ways([1, 1, 2, 3]) == 12
    assert digit_box_ways([1, 1, 2, 2]) == 6
    assert digit_box_ways([1, 1, 1, 2]) == 4
    assert digit_box_ways([1, 1, 1, 1]) == 1
    assert digit_box_ways([1, 2, 3]) == 6
    assert digit_box_ways([1, 1, 2]) == 3
    assert GAMES["Pick 4 + FIREBALL"]["plays"]["Box (4-way)"] == 1200


def test_parse_tokens_and_digits() -> None:
    assert parse_int_tokens("02 04 10 48 56") == [2, 4, 10, 48, 56]
    assert parse_int_tokens("02-04-10-48-56") == [2, 4, 10, 48, 56]
    assert parse_digit_row("1234", 4) == [1, 2, 3, 4]
    assert parse_digit_row("012", 3) == [0, 1, 2]
    assert parse_digit_row("7 8 9 0", 4) == [7, 8, 9, 0]


def test_export_csv_preload() -> None:
    df, err = load_game_history("Mega Millions", None, data_dir=APP_DIR)
    assert err is None, err
    assert df is not None and len(df) >= 2000
    assert {"W1", "W2", "W3", "W4", "W5", "Bonus", "white_set"} <= set(df.columns)
    assert df["Bonus"].min() >= 1
    first = df.iloc[0]
    assert len(first["white_set"]) == 5


def test_parse_rejects_wrong_game_shape() -> None:
    raw = pd.DataFrame({"Draw Date": ["01/01/2026"], "Winning Numbers": ["7"]})
    try:
        parse_history(GAMES["Mega Millions"], raw)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a 1-number Mega Millions row")


def test_generators_stay_in_range() -> None:
    for game in GAMES:
        g = GAMES[game]
        for method in ("secure", "quantum", "anti", "hotcold"):
            freq = Counter({i: 10 - (i % 5) for i in range(1, (g.get("n") or 10) + 1)})
            pick, src = generate(game, method, freq=freq, mode="hot", intention="test")
            assert src
            if "whites" in pick:
                assert len(pick["whites"]) == g["k"]
                assert len(set(pick["whites"])) == g["k"]
                assert all(1 <= x <= g["n"] for x in pick["whites"])
                if method == "anti" and g["n"] - 32 + 1 >= g["k"]:
                    assert all(x >= 32 for x in pick["whites"])
                if g.get("bonus_n"):
                    assert 1 <= pick["bonus"] <= g["bonus_n"]
            elif "digits" in pick:
                assert len(pick["digits"]) == g["d"]
                assert all(0 <= d <= 9 for d in pick["digits"])
                assert 0 <= pick["fireball"] <= 9
            else:
                assert 1 <= pick["pop"] <= g["n"]
            assert format_pick_plain(pick)


def test_never_drawn_respects_history() -> None:
    seen = {frozenset({1, 2, 3, 4, 5})}
    pick, src, tries = never_drawn_pick("Mega Millions", seen, max_tries=200)
    assert frozenset(pick["whites"]) not in seen
    assert tries >= 1
    assert "history filter" in src


if __name__ == "__main__":
    tests = [
        test_mega_millions_odds,
        test_powerball_odds,
        test_palmetto_odds_and_price,
        test_digit_box_ways,
        test_parse_tokens_and_digits,
        test_export_csv_preload,
        test_parse_rejects_wrong_game_shape,
        test_generators_stay_in_range,
        test_never_drawn_respects_history,
    ]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(tests)} checks passed")
