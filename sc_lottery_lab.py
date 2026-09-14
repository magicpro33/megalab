"""
SC LOTTERY ANALYSIS LAB — an AI Upscale LLC tool
=================================================
All six South Carolina Education Lottery terminal games:
  Mega Millions · Powerball · Palmetto Cash 5 · Pick 4 + FIREBALL ·
  Pick 3 + FIREBALL · CASH POP

Run:  streamlit run sc_lottery_lab.py
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from lottery_core import (
    GAMES,
    any_prize_probability,
    digit_box_ways,
    expected_multiplier,
    format_pick_markdown,
    format_pick_plain,
    generate,
    load_game_history,
    matrix_tier_probability,
    never_drawn_pick,
)

APP_DIR = Path(__file__).resolve().parent
GAME_NAMES = list(GAMES.keys())
PAGES = [
    "Number Generators",
    "My Picks",
    "Frequency Analysis",
    "Check My Numbers",
    "Odds & Expected Value",
]

st.set_page_config(
    page_title="SC Lottery Analysis Lab | AI Upscale",
    page_icon="🎰",
    layout="wide",
)

# Drop widget keys from older builds so a type change cannot blank the app.
for _stale in ("game_select", "game_pick"):
    st.session_state.pop(_stale, None)

if "picks" not in st.session_state:
    st.session_state.picks = []
if "last_pick" not in st.session_state:
    st.session_state.last_pick = None


@st.cache_data(show_spinner=False)
def cached_history(name: str, file_bytes: bytes | None):
    return load_game_history(name, file_bytes, data_dir=APP_DIR)


def anu_key() -> str | None:
    try:
        key = st.secrets.get("ANU_QRNG_KEY")
    except Exception:
        return None
    return str(key) if key else None


def slug(name: str) -> str:
    return name.replace(" ", "_")


def compatible_history(game: dict, frame: pd.DataFrame | None) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    if game["kind"] == "matrix":
        cols = [f"W{i + 1}" for i in range(game["k"])] + ["white_set"]
        if game.get("bonus_n"):
            cols.append("Bonus")
        return frame if all(c in frame.columns for c in cols) else None
    if game["kind"] == "digit":
        cols = [f"D{i + 1}" for i in range(game["d"])] + ["digit_str", "digit_sorted"]
        return frame if all(c in frame.columns for c in cols) else None
    return frame if "Pop" in frame.columns else None


def history_flags(pick: dict, game: dict, df: pd.DataFrame | None, pop_freq: Counter, history_sets: set, full_combo_set: set) -> list[str]:
    if df is None:
        return ["no history file loaded — upload one in the sidebar to enable history checks"]
    if "whites" in pick:
        ws = frozenset(pick["whites"])
        if "bonus" in pick and (ws, pick["bonus"]) in full_combo_set:
            return ["exact combo (mains + bonus) has hit the jackpot in your file ⚠️"]
        if ws in history_sets:
            return [f"{game['k']}-ball set has appeared before (different bonus or no bonus) ⚠️"]
        return [f"{game['k']}-ball set **never drawn** in your file ✅"]
    if "digits" in pick:
        s = "".join(map(str, pick["digits"]))
        hits = int((df["digit_str"] == s).sum())
        box = int((df["digit_sorted"] == "".join(sorted(s))).sum())
        return [
            f"drawn straight **{hits}×**, box **{box}×** in your file "
            f"(with only {10 ** game['d']:,} combos, repeats are routine)"
        ]
    return [f"popped **{pop_freq.get(pick['pop'], 0)}×** in your file"]


def save_pick(game_name: str, pick: dict, source: str, intention: str | None = None, attempts: int | None = None) -> None:
    st.session_state.picks.append(
        {
            "#": len(st.session_state.picks) + 1,
            "Generated At": pd.Timestamp.now().strftime("%m/%d/%Y %I:%M:%S %p"),
            "Game": game_name,
            "Numbers": format_pick_plain(pick),
            "Source": source,
            "Intention": intention or "",
        }
    )
    st.session_state.last_pick = {
        "game": game_name,
        "pick": pick,
        "source": source,
        "intention": intention,
        "attempts": attempts,
    }
    st.toast("Pick saved to My Picks", icon="💾")


def show_pick(pick: dict, source: str, game: dict, flags: list[str], intention: str | None = None, attempts: int | None = None) -> None:
    st.markdown(f"### {format_pick_markdown(pick, game.get('bonus_name'))}")
    bits = [f"Source: **{source}**"]
    if attempts:
        bits.append(f"attempts to find never-drawn set: {attempts}")
    bits += flags
    if intention:
        bits.append(f"intention: *{intention}*")
    st.caption(" · ".join(bits))


def page_generators(game_name: str, game: dict, gkey: str, df, white_freq, digit_freq, pop_freq, history_sets, full_combo_set) -> None:
    last = st.session_state.last_pick
    if last and last.get("game") == game_name:
        show_pick(
            last["pick"],
            last["source"],
            game,
            history_flags(last["pick"], game, df, pop_freq, history_sets, full_combo_set),
            last.get("intention"),
            last.get("attempts"),
        )

    st.subheader("Intention generator")
    st.caption(
        "Your intention is SHA-256 hashed and mixed with random bytes. "
        "The distribution stays uniform — this is a ritual, not an edge."
    )
    ic1, ic2 = st.columns([3, 1])
    intention = ic1.text_input(
        "Your intention",
        placeholder="e.g., abundance for my family",
        label_visibility="collapsed",
        key=f"intention_{gkey}",
    )
    if ic2.button("Commit intention", type="primary", key=f"btn_int_{gkey}"):
        if not str(intention).strip():
            st.warning("Set an intention first — even one word.")
        else:
            pick, src = generate(game_name, "intention", intention=intention, api_key=anu_key())
            save_pick(game_name, pick, src, intention=str(intention).strip())
            show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set), str(intention).strip())

    left, right = st.columns(2)
    with left:
        st.subheader("Quantum pick")
        if st.button("Generate quantum numbers", type="primary", key=f"btn_q_{gkey}"):
            pick, src = generate(game_name, "quantum", api_key=anu_key())
            save_pick(game_name, pick, src)
            show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set))

        st.subheader("Crypto-secure quick pick")
        if st.button("Generate secure pick", key=f"btn_sec_{gkey}"):
            pick, src = generate(game_name, "secure", api_key=anu_key())
            save_pick(game_name, pick, src)
            show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set))

        if game["kind"] == "matrix":
            st.subheader("Never-drawn main-ball set")
            if df is None:
                st.caption("Upload a history file to enable.")
            elif st.button("Generate virgin combination", key=f"btn_virgin_{gkey}"):
                pick, src, tries = never_drawn_pick(game_name, history_sets, api_key=anu_key())
                save_pick(game_name, pick, src, attempts=tries)
                show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set), attempts=tries)
        else:
            st.subheader("Never-drawn?")
            st.caption(f"Not offered for {game_name} — too few outcomes, repeats are normal.")

    with right:
        if game["kind"] == "matrix" and game["n"] > 40:
            st.subheader("Anti-popularity pick")
            st.caption("Main balls > 31 to dodge birthday pickers. Same win odds; fewer shared jackpots.")
            if st.button("Generate anti-popularity pick", key=f"btn_anti_{gkey}"):
                pick, src = generate(game_name, "anti", api_key=anu_key())
                save_pick(game_name, pick, src)
                show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set))
        else:
            st.subheader("Anti-popularity?")
            st.caption("Fixed prizes here — unpopular numbers do not pay more.")

        freq_for_game = white_freq if game["kind"] == "matrix" else digit_freq if game["kind"] == "digit" else pop_freq
        st.subheader("Hot pick")
        if df is None or not freq_for_game:
            st.caption("Upload a history file to enable hot/cold picks.")
        else:
            st.caption("Sampled from the most-drawn numbers. Entertainment only.")
            if st.button("Generate hot pick", key=f"btn_hot_{gkey}"):
                if game["kind"] == "pop":
                    pick, src = {"pop": freq_for_game.most_common(1)[0][0]}, "Most-drawn CASH POP number"
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="hot")
                save_pick(game_name, pick, src)
                show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set))

            st.subheader("Cold pick")
            st.caption("Least-drawn numbers. 'Due' is the gambler's fallacy.")
            if st.button("Generate cold pick", key=f"btn_cold_{gkey}"):
                if game["kind"] == "pop":
                    ranked = [n for n, _ in freq_for_game.most_common()]
                    ranked += [n for n in range(1, game["n"] + 1) if n not in ranked]
                    pick, src = {"pop": ranked[-1]}, "Least-drawn CASH POP number"
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="cold")
                save_pick(game_name, pick, src)
                show_pick(pick, src, game, history_flags(pick, game, df, pop_freq, history_sets, full_combo_set))


def page_picks() -> None:
    st.subheader("Every number you've generated this session")
    if not st.session_state.picks:
        st.info("No picks yet — every pick from any game is saved here automatically.")
        return
    picks_df = pd.DataFrame(st.session_state.picks)
    st.dataframe(picks_df, hide_index=True, width="stretch")
    d1, d2, d3 = st.columns([1, 1, 2])
    d1.download_button(
        "Download picks CSV",
        picks_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"my_sc_lottery_picks_{date.today():%Y%m%d}.csv",
        mime="text/csv",
        type="primary",
        key="dl_picks",
    )
    if d2.button("Clear all picks", key="clear_picks"):
        st.session_state.picks = []
        st.session_state.last_pick = None
        st.rerun()
    d3.caption(f"{len(picks_df)} pick(s). Session-based — download before closing the tab.")


def page_frequency(game_name: str, game: dict, gkey: str, df: pd.DataFrame | None) -> None:
    if df is None or df.empty:
        st.info(f"No history loaded for {game_name}. Upload a CSV in the sidebar to unlock frequency analysis.")
        return

    dfe = df
    if game["kind"] == "matrix" and game.get("era_start") is not None:
        options = ["Current rules era", "All draws in file"]
        if game.get("white70_start") is not None:
            options.insert(1, "White balls 1–70 era (since Oct 2017)")
        era_choice = st.radio("History window", options, index=0, horizontal=True, key=f"era_{gkey}")
        if era_choice.startswith("Current"):
            dfe = df[df["Draw Date"] >= game["era_start"]]
        elif era_choice.startswith("White"):
            dfe = df[df["Draw Date"] >= game["white70_start"]]
        if dfe.empty:
            st.warning("No draws in that window — showing the full file instead.")
            dfe = df

    c1, c2 = st.columns(2)
    c1.metric("Draws analyzed", f"{len(dfe):,}")
    c2.metric("Date range", f"{dfe['Draw Date'].min():%b %Y} – {dfe['Draw Date'].max():%b %Y}")

    if game["kind"] == "matrix":
        wf_c = Counter(dfe[[f"W{i + 1}" for i in range(game["k"])]].to_numpy().ravel())
        wf = pd.DataFrame(
            {"Number": range(1, game["n"] + 1), "Times Drawn": [wf_c.get(x, 0) for x in range(1, game["n"] + 1)]}
        )
        st.subheader(f"Main balls (1–{game['n']})")
        st.caption(
            f"Uniform expectation: {len(dfe) * game['k'] / game['n']:.1f} per number — "
            "deviations are normal sampling noise."
        )
        st.bar_chart(wf.set_index("Number"))
        h1, h2 = st.columns(2)
        h1.markdown("**Hottest 10**")
        h1.dataframe(wf.nlargest(10, "Times Drawn"), hide_index=True, width="stretch")
        h2.markdown("**Coldest 10**")
        h2.dataframe(wf.nsmallest(10, "Times Drawn"), hide_index=True, width="stretch")
        if game.get("bonus_n") and "Bonus" in dfe.columns:
            bf_c = Counter(dfe["Bonus"])
            bonus_hi = int(game["bonus_n"])
            extra = [int(x) for x in bf_c if int(x) > bonus_hi]
            st.subheader(f"{game['bonus_name']} (1–{bonus_hi} under current rules)")
            if extra:
                st.caption(f"{len(extra)} historical bonus values sit above {bonus_hi} and are omitted from this chart.")
            bf = pd.DataFrame(
                {"Number": range(1, bonus_hi + 1), "Times Drawn": [bf_c.get(x, 0) for x in range(1, bonus_hi + 1)]}
            )
            st.bar_chart(bf.set_index("Number"))
        return

    if game["kind"] == "digit":
        pos_freq = Counter(dfe[[f"D{i + 1}" for i in range(game["d"])]].to_numpy().ravel())
        st.subheader("Digit frequency — overall")
        st.bar_chart(
            pd.DataFrame({"Digit": range(10), "Times Drawn": [pos_freq.get(x, 0) for x in range(10)]}).set_index("Digit")
        )
        st.subheader("Digit frequency — by position")
        pos_cols = st.columns(game["d"])
        for i in range(game["d"]):
            pc = Counter(dfe[f"D{i + 1}"])
            with pos_cols[i]:
                st.markdown(f"**Position {i + 1}**")
                st.dataframe(
                    pd.DataFrame({"Digit": range(10), "×": [pc.get(x, 0) for x in range(10)]}),
                    hide_index=True,
                    width="stretch",
                    height=240,
                )
        top = dfe["digit_str"].value_counts()
        t1, t2 = st.columns(2)
        t1.markdown("**Most repeated**")
        t1.dataframe(top.head(10).rename_axis("Combo").reset_index(name="Times"), hide_index=True, width="stretch")
        t2.metric("Distinct combos seen", f"{dfe['digit_str'].nunique():,} of {10 ** game['d']:,}")
        return

    pop_c = Counter(dfe["Pop"])
    st.subheader("CASH POP number frequency (1–15)")
    st.bar_chart(
        pd.DataFrame({"Number": range(1, 16), "Times Drawn": [pop_c.get(x, 0) for x in range(1, 16)]}).set_index("Number")
    )
    st.caption(f"Uniform expectation: {len(dfe) / 15:.1f} per number.")


def page_check(game_name: str, game: dict, gkey: str, df: pd.DataFrame | None) -> None:
    st.subheader(f"Check numbers against {game_name} history")
    if df is None or df.empty:
        st.info("Upload a history CSV in the sidebar to enable checking.")
        return

    if game["kind"] == "matrix":
        cols = st.columns(game["k"] + (1 if game.get("bonus_n") else 0))
        whites_in = [
            int(
                cols[i].number_input(
                    f"Ball {i + 1}",
                    min_value=1,
                    max_value=int(game["n"]),
                    value=min(7 * (i + 1), int(game["n"])),
                    step=1,
                    key=f"cw_{gkey}_{i}",
                )
            )
            for i in range(game["k"])
        ]
        bonus_in = (
            int(
                cols[-1].number_input(
                    game["bonus_name"],
                    min_value=1,
                    max_value=int(game["bonus_n"]),
                    value=7,
                    step=1,
                    key=f"cb_{gkey}",
                )
            )
            if game.get("bonus_n")
            else None
        )
        if not st.button("Check history", type="primary", key=f"check_{gkey}"):
            return
        if len(set(whites_in)) != game["k"]:
            st.error("Main balls must all be different.")
            return
        ws = frozenset(whites_in)
        five = df[df["white_set"] == ws]
        if game.get("bonus_n"):
            exact = five[five["Bonus"] == bonus_in]
            if len(exact):
                st.error(f"Exact combo hit the JACKPOT on {exact.iloc[0]['Draw Date']:%m/%d/%Y}.")
            elif len(five):
                st.warning(
                    f"The {game['k']} main balls hit together on "
                    f"{five.iloc[0]['Draw Date']:%m/%d/%Y} (different {game['bonus_name']})."
                )
            else:
                st.success("Never drawn in your file.")
        elif len(five):
            st.error(f"This set won the JACKPOT on {five.iloc[0]['Draw Date']:%m/%d/%Y}.")
        else:
            st.success("Never drawn in your file.")

        rows = []
        for _, r in df.iterrows():
            wm = len(ws & r["white_set"])
            bm = (bonus_in == r["Bonus"]) if game.get("bonus_n") else None
            label = next((t[3] for t in game["tiers"] if t[0] == wm and (t[1] is None or t[1] == bm)), None)
            if label:
                rows.append(
                    {
                        "Draw Date": r["Draw Date"].date(),
                        "Matched": f"{wm}" + (f" + {game['bonus_name']}" if bm else ""),
                        "Tier": label,
                    }
                )
        if rows:
            st.markdown(f"**Draws where these numbers would have won: {len(rows)}**")
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("These numbers would never have won any tier in the file.")
        return

    if game["kind"] == "digit":
        cols = st.columns(game["d"])
        digs = [
            int(
                cols[i].number_input(
                    f"Digit {i + 1}",
                    min_value=0,
                    max_value=9,
                    value=min(i + 1, 9),
                    step=1,
                    key=f"cd_{gkey}_{i}",
                )
            )
            for i in range(game["d"])
        ]
        if not st.button("Check history", type="primary", key=f"check_{gkey}"):
            return
        s = "".join(map(str, digs))
        straight = df[df["digit_str"] == s]
        box = df[df["digit_sorted"] == "".join(sorted(s))]
        m1, m2, m3 = st.columns(3)
        m1.metric("Straight hits", len(straight))
        m2.metric("Box hits", len(box))
        m3.metric("Box type", f"{digit_box_ways(digs)}-way")
        if len(box):
            st.dataframe(
                box[["Draw Date", "digit_str"]].head(25).rename(columns={"digit_str": "Drawn"}),
                hide_index=True,
                width="stretch",
            )
        return

    pop_in = int(
        st.number_input("Your CASH POP number", min_value=1, max_value=15, value=7, step=1, key=f"cp_{gkey}")
    )
    if st.button("Check history", type="primary", key=f"check_{gkey}"):
        hits = df[df["Pop"] == pop_in]
        st.metric(f"Number {pop_in} popped", f"{len(hits)}× in {len(df)} drawings", delta=f"expected {len(df) / 15:.1f}")


def page_odds(game_name: str, game: dict, gkey: str) -> None:
    st.subheader(f"{game_name} — exact odds & expected value")

    if game["kind"] == "matrix":
        st.caption(
            f"Hypergeometric odds for {game['k']} balls from 1–{game['n']}"
            + (f" plus {game['bonus_name']} 1–{game['bonus_n']}." if game.get("bonus_n") else ".")
        )
        jc1, jc2 = st.columns(2)
        jackpot = jc1.number_input(
            "Jackpot CASH value ($)",
            min_value=10_000,
            value=int(game["default_jackpot"]),
            step=10_000,
            format="%d",
            key=f"jp_{gkey}",
        )
        co = (
            jc2.number_input(
                "Expected winners sharing jackpot",
                min_value=1.0,
                value=1.0,
                step=0.25,
                key=f"co_{gkey}",
            )
            if game.get("sharing")
            else 1.0
        )
        em = expected_multiplier(game.get("multipliers"))
        with st.expander("Edit non-jackpot base prize amounts"):
            st.caption("Official base (pre-multiplier) prizes. Verify against the current rules PDF.")
            for idx, (_km, _bm, prize, label) in enumerate(game["tiers"]):
                if prize is not None:
                    st.number_input(label, min_value=0, value=int(prize), step=1, key=f"prize_{gkey}_{idx}")

        rows, ev = [], 0.0
        st.markdown("**Prize table**")
        for idx, (km, bm, prize, label) in enumerate(game["tiers"]):
            p = matrix_tier_probability(game, km, bm)
            if prize is None:
                val = jackpot / max(co, 1.0)
                shown = "JACKPOT"
                avg_prize = val
            else:
                val = float(st.session_state.get(f"prize_{gkey}_{idx}", prize))
                shown = f"{val:,.0f}"
                avg_prize = val * em
            contrib = p * avg_prize
            ev += contrib
            row = {
                "Tier": label,
                "Odds": f"1 in {round(1 / p):,}",
                "Base prize ($)": shown,
                "EV contribution ($)": f"{contrib:.4f}",
            }
            if em > 1.01 and prize is not None:
                row["Expected prize ($)"] = f"{avg_prize:,.0f}"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        any_p = any_prize_probability(game)
        e1, e2, e3 = st.columns(3)
        e1.metric("Any prize", f"1 in {1 / any_p:.2f}")
        e2.metric(f"EV per ${game['price']:.0f} ticket", f"${ev:.2f}")
        e3.metric(
            "Expected loss per ticket",
            f"${game['price'] - ev:.2f}",
            delta=f"{(ev / game['price'] - 1) * 100:.0f}% return",
            delta_color="inverse",
        )
        if em > 1.01:
            st.caption(f"Non-jackpot prizes include the built-in multiplier (expected {em:.2f}×). Jackpot is never multiplied.")
        official = game.get("official_any_odds")
        if official:
            st.caption(f"Published overall odds: 1 in {official:g}. Computed: 1 in {1 / any_p:.2f}.")
        return

    if game["kind"] == "digit":
        st.markdown("Enter the digits you'd play — box odds depend on repeats:")
        cols = st.columns(game["d"])
        digs = [
            int(
                cols[i].number_input(
                    f"Digit {i + 1}",
                    min_value=0,
                    max_value=9,
                    value=min(i + 1, 9),
                    step=1,
                    key=f"od_{gkey}_{i}",
                )
            )
            for i in range(game["d"])
        ]
        ways = digit_box_ways(digs)
        total = 10 ** game["d"]
        with st.expander("Edit payouts"):
            st.number_input("Straight payout", min_value=0, value=int(game["plays"]["Straight"]), step=1, key=f"pay_{gkey}_straight")
            if ways > 1:
                default_box = game["plays"].get(
                    f"Box ({ways}-way)",
                    round(game["plays"]["Straight"] / ways / 5) * 5,
                )
                st.number_input("Box payout", min_value=0, value=int(default_box), step=1, key=f"pay_{gkey}_box")

        straight_pay = float(st.session_state.get(f"pay_{gkey}_straight", game["plays"]["Straight"]))
        rows = [
            {
                "Play": "Straight (exact order)",
                "Odds": f"1 in {total:,}",
                "Payout per $1": f"${straight_pay:,.0f}",
                "EV per $1": f"${straight_pay / total:.3f}",
            }
        ]
        if ways > 1:
            box_label = f"Box ({ways}-way)"
            box_pay = float(
                st.session_state.get(
                    f"pay_{gkey}_box",
                    game["plays"].get(box_label, round(straight_pay / ways / 5) * 5),
                )
            )
            rows.append(
                {
                    "Play": f"{box_label} (any order)",
                    "Odds": f"1 in {total // ways:,}",
                    "Payout per $1": f"${box_pay:,.0f}",
                    "EV per $1": f"${box_pay * ways / total:.3f}",
                }
            )
        else:
            rows.append({"Play": "Box", "Odds": "n/a — all digits identical (straight only)", "Payout per $1": "—", "EV per $1": "—"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "FIREBALL doubles the wager and adds a substitute digit at reduced payouts. "
            f"Official FIREBALL odds: {'1 in 37 to 1 in 10,000' if game['d'] == 3 else '1 in 149 to 1 in 100,000'}."
        )
        return

    st.markdown(
        "- **Odds of winning: exactly 1 in 15.**\n"
        "- Prize amount is assigned at purchase, so EV is not published per ticket.\n"
        "- Buying all 15 numbers guarantees a win only if that prize beats 15× the wager."
    )
    st.metric("Win probability", "1 in 15 (6.67%)")


def render_app() -> None:
    st.markdown(
        """
<style>
[data-testid="stHeader"] { background: transparent; }
.aiu-header { display: flex; align-items: center; gap: 18px; padding: 6px 0 14px 0; border-bottom: 1px solid #24365A; margin-bottom: 10px; }
.aiu-header img { height: 104px; }
.aiu-footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid #24365A; font-size: 0.85rem; color: #8FA3C8; }
.aiu-footer a, .aiu-header a { color: inherit; text-decoration: none; }
.aiu-footer a:hover { color: #F5A623; }
</style>
<div class="aiu-header">
  <a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">
    <img src="https://aiupscalellc.netlify.app/logo.svg" alt="AI Upscale LLC">
  </a>
  <div>
    <div style="font-family:sans-serif;font-size:1.9rem;font-weight:700;color:#F5A623;line-height:1;">
      SC LOTTERY ANALYSIS LAB
    </div>
    <div style="color:#8FA3C8;font-size:0.9rem;">
      All 6 SCEL terminal games · quantum picks · exact odds engine — an
      <a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">AI Upscale LLC</a> tool
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Game")
        game_name = st.radio("Select game", GAME_NAMES, key="nav_game")
        page = st.radio("Page", PAGES, key="nav_page")
        st.divider()
        st.header("Data")
        up = st.file_uploader(
            f"Upload {game_name} history CSV",
            type="csv",
            key="history_csv",
            help="Needs a date column and a winning-numbers column (space, dash, or comma separated).",
        )
        st.divider()
        st.subheader("Reality check")
        st.markdown(
            "Every combination has identical odds every draw. Frequency stats describe the past; "
            "they don't predict. Play for fun, with money you can afford to lose. "
            "[Play Responsibly SC](https://www.sceducationlottery.com/PlayResponsibly)"
        )

    game = GAMES[game_name]
    gkey = slug(game_name)
    st.caption(f"**{game_name}** — {game['note']}")

    raw_df, load_error = cached_history(game_name, up.getvalue() if up else None)
    df = compatible_history(game, raw_df)
    if load_error:
        st.sidebar.error(load_error)
    elif raw_df is not None and df is None:
        st.sidebar.error("That CSV does not match this game's number format.")
    elif df is not None:
        st.sidebar.success(f"{len(df):,} {game_name} draws loaded")
    elif game.get("preload"):
        st.sidebar.warning("Preloaded Mega Millions file is missing from the app folder.")
    else:
        st.sidebar.info("No history file for this game yet.")

    white_freq: Counter = Counter()
    digit_freq: Counter = Counter()
    pop_freq: Counter = Counter()
    history_sets: set = set()
    full_combo_set: set = set()
    if df is not None:
        if game["kind"] == "matrix":
            white_freq = Counter(df[[f"W{i + 1}" for i in range(game["k"])]].to_numpy().ravel())
            history_sets = set(df["white_set"])
            if game.get("bonus_n"):
                full_combo_set = set(zip(df["white_set"], df["Bonus"]))
            else:
                full_combo_set = set(history_sets)
        elif game["kind"] == "digit":
            digit_freq = Counter(df[[f"D{i + 1}" for i in range(game["d"])]].to_numpy().ravel())
        else:
            pop_freq = Counter(df["Pop"])

    if page == "Number Generators":
        page_generators(game_name, game, gkey, df, white_freq, digit_freq, pop_freq, history_sets, full_combo_set)
    elif page == "My Picks":
        page_picks()
    elif page == "Frequency Analysis":
        page_frequency(game_name, game, gkey, df)
    elif page == "Check My Numbers":
        page_check(game_name, game, gkey, df)
    else:
        page_odds(game_name, game, gkey)

    st.markdown(
        '<div class="aiu-footer">Built by '
        '<a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">AI Upscale LLC</a>'
        " · Columbia, SC · For entertainment and education — play responsibly · "
        '<a href="https://www.sceducationlottery.com/PlayResponsibly" target="_blank" rel="noopener">'
        "Play Responsibly SC</a></div>",
        unsafe_allow_html=True,
    )


try:
    render_app()
except Exception as exc:
    st.error("The app hit an error while rendering. The details are below — switch games again after a refresh if the page was blank.")
    st.exception(exc)
