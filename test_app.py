"""Backtest: every game × every page, plus generate / check / odds."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from lottery_core import GAMES

PAGES = [
    "Number Generators",
    "My Picks",
    "Frequency Analysis",
    "Check My Numbers",
    "Odds & Expected Value",
]


def run(at: AppTest) -> AppTest:
    at.run(timeout=45)
    if at.exception:
        raise AssertionError(at.exception)
    return at


def set_nav(at: AppTest, game: str, page: str) -> AppTest:
    at.session_state["nav_game"] = game
    at.session_state["nav_page"] = page
    return run(at)


def main() -> None:
    at = run(AppTest.from_file("sc_lottery_lab.py"))
    print("ok  initial render")

    for game in GAMES:
        for page in PAGES:
            set_nav(at, game, page)
            print(f"ok  {game} / {page}")

    set_nav(at, "Mega Millions", "Number Generators")
    secure = next(b for b in at.button if b.label == "Generate secure pick")
    secure.click()
    run(at)
    assert at.session_state["picks"], "secure pick was not saved"
    print("ok  MM secure pick", at.session_state["picks"][-1]["Numbers"])

    virgin = next(b for b in at.button if b.label == "Generate virgin combination")
    virgin.click()
    run(at)
    print("ok  MM virgin", at.session_state["picks"][-1]["Numbers"])

    set_nav(at, "Mega Millions", "Check My Numbers")
    next(b for b in at.button if b.label == "Check history").click()
    run(at)
    print("ok  MM check history")

    set_nav(at, "Mega Millions", "Odds & Expected Value")
    print("ok  MM odds stay up")

    set_nav(at, "Powerball", "Odds & Expected Value")
    print("ok  Powerball odds")

    set_nav(at, "Palmetto Cash 5", "Odds & Expected Value")
    print("ok  Palmetto odds")

    set_nav(at, "Pick 3 + FIREBALL", "Odds & Expected Value")
    print("ok  Pick 3 odds")

    set_nav(at, "Pick 4 + FIREBALL", "Number Generators")
    next(b for b in at.button if b.label == "Generate secure pick").click()
    run(at)
    print("ok  Pick 4 pick", at.session_state["picks"][-1]["Numbers"])

    set_nav(at, "CASH POP", "Number Generators")
    next(b for b in at.button if b.label == "Generate secure pick").click()
    run(at)
    print("ok  CASH POP pick", at.session_state["picks"][-1]["Numbers"])

    set_nav(at, "Powerball", "Frequency Analysis")
    set_nav(at, "Mega Millions", "Frequency Analysis")
    set_nav(at, "CASH POP", "My Picks")
    print("ok  cross-game page hops")

    print(f"\nBacktest passed — {len(GAMES) * len(PAGES)} game/page renders plus actions")


if __name__ == "__main__":
    main()
