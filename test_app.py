"""Streamlit AppTest smoke checks for every game and tab."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

GAMES = [
    "Mega Millions",
    "Powerball",
    "Palmetto Cash 5",
    "Pick 4 + FIREBALL",
    "Pick 3 + FIREBALL",
    "CASH POP",
]


def _run(at: AppTest) -> AppTest:
    at.run(timeout=30)
    if at.exception:
        raise AssertionError(at.exception)
    return at


def main() -> None:
    at = _run(AppTest.from_file("sc_lottery_lab.py"))
    print("ok  initial render")

    print("  widgets", len(at.button), "buttons")

    # Switch through every game and confirm no exception.
    for game in GAMES:
        at.session_state["game_pick"] = game
        _run(at)
        print(f"ok  switch {game}")

    # Mega Millions: generate a secure pick and check history.
    at.session_state["game_pick"] = "Mega Millions"
    _run(at)
    labels = [b.label for b in at.button]
    secure = next(b for b in at.button if b.label == "Generate secure pick")
    secure.click()
    _run(at)
    assert at.session_state["picks"], "secure pick was not saved"
    print("ok  secure pick saved:", at.session_state["picks"][-1]["Numbers"])

    check = next(b for b in at.button if b.label == "Check history")
    check.click()
    _run(at)
    print("ok  check history")

    virgin = next((b for b in at.button if b.label == "Generate virgin combination"), None)
    if virgin:
        virgin.click()
        _run(at)
        print("ok  virgin combo", at.session_state["picks"][-1]["Numbers"])

    # Digit game odds widgets
    at.session_state["game_pick"] = "Pick 3 + FIREBALL"
    _run(at)
    print("ok  pick 3 render")

    at.session_state["game_pick"] = "CASH POP"
    _run(at)
    print("ok  cash pop render")

    print("\nAppTest smoke checks passed")


if __name__ == "__main__":
    main()
