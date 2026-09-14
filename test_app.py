"""Smoke-test the original selectbox + tabs UI."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from lottery_core import GAMES


def run(at: AppTest) -> AppTest:
    at.run(timeout=45)
    if at.exception:
        raise AssertionError(at.exception)
    return at


def main() -> None:
    at = run(AppTest.from_file("sc_lottery_lab.py"))
    print("ok  initial render")
    sb = at.selectbox[0]
    for game in GAMES:
        sb.set_value(game)
        run(at)
        print(f"ok  switch {game}")
    print("\nSelectbox + tabs smoke test passed")


if __name__ == "__main__":
    main()
