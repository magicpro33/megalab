"""
SC LOTTERY ANALYSIS LAB — an AI Upscale LLC tool
=================================================
All six South Carolina Education Lottery terminal games:
  Mega Millions · Powerball · Palmetto Cash 5 · Pick 4 + FIREBALL ·
  Pick 3 + FIREBALL · CASH POP

Frequency analysis | History checker | Quantum / secure / intention picks |
Never-drawn combos | Exact odds & expected-value engine per game

Matrices verified against official SCEL / Mega Millions / Powerball rules.
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

st.set_page_config(
    page_title="SC Lottery Analysis Lab | AI Upscale",
    page_icon="🎰",
    layout="wide",
)

if "picks" not in st.session_state:
    st.session_state.picks = []
if "last_pick" not in st.session_state:
    st.session_state.last_pick = None


def _anu_key() -> str | None:
    try:
        key = st.secrets.get("ANU_QRNG_KEY")
    except Exception:
        return None
    return str(key) if key else None


st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label { font-family: 'Plus Jakarta Sans', sans-serif; }
h1, h2, h3, h4, [data-testid="stMetricValue"] { font-family: 'Rajdhani', sans-serif !important; letter-spacing: 0.02em; }
h1 { color: #F5A623 !important; }
h2, h3 { color: #F4EDE4 !important; }
[data-testid="stMetricValue"] { color: #F5A623 !important; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] { background: #13203A; border-radius: 8px 8px 0 0; font-family: 'Rajdhani', sans-serif; font-weight: 600; }
.stTabs [aria-selected="true"] { background: #F5A623 !important; color: #0A1220 !important; }
.stButton > button { font-family: 'Rajdhani', sans-serif; font-weight: 600; border: 1px solid #F5A623; }
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
    <div style="font-family:'Rajdhani',sans-serif;font-size:1.9rem;font-weight:700;color:#F5A623;line-height:1;">
      🎰 SC LOTTERY ANALYSIS LAB
    </div>
    <div style="color:#8FA3C8;font-size:0.9rem;">
      All 6 SCEL terminal games · quantum picks · exact odds engine — an
      <a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener"
         style="color:inherit;text-decoration:none;">AI Upscale LLC</a> tool
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

game_name = st.selectbox("🎯 Select game", list(GAMES.keys()), key="game_select")
g = GAMES[game_name]
st.caption(g["note"])
gkey = game_name.replace(" ", "_")

with st.sidebar:
    st.header("Data")
    up = st.file_uploader(
        f"Upload {game_name} history CSV",
        type="csv",
        key=f"upload_{gkey}",
        help=(
            "Needs a date column and a winning-numbers column "
            "(space, dash, or comma separated). Mega Millions history is preloaded."
        ),
    )
    st.divider()
    st.subheader("⚖️ Reality check")
    st.markdown(
        "Every combination in every draw game has identical odds, every draw — balls and "
        "digits have no memory. Frequency stats describe the past; they don't predict. "
        "Fixed-prize games (Pick 3/4, CASH POP) can't even benefit from unpopular numbers. "
        "Play for fun, with money you can afford to lose. "
        "[Play Responsibly SC](https://www.sceducationlottery.com/PlayResponsibly)"
    )

@st.cache_data(show_spinner=False)
def _cached_history(name: str, file_bytes: bytes | None) -> tuple[pd.DataFrame | None, str | None]:
    return load_game_history(name, file_bytes, data_dir=APP_DIR)


df, load_error = _cached_history(game_name, up.getvalue() if up else None)

if load_error:
    st.sidebar.error(load_error)
elif df is not None:
    st.sidebar.success(f"{len(df):,} {game_name} draws loaded")
elif g.get("preload"):
    st.sidebar.warning("Preloaded Mega Millions file is missing from the app folder.")
else:
    st.sidebar.info("No history file for this game yet — upload a CSV to unlock analysis.")

white_freq: Counter = Counter()
digit_freq: Counter = Counter()
pop_freq: Counter = Counter()
bonus_freq: Counter = Counter()
history_sets: set = set()
full_combo_set: set = set()
if df is not None and not df.empty:
    if g["kind"] == "matrix":
        white_freq = Counter(df[[f"W{i + 1}" for i in range(g["k"])]].to_numpy().ravel())
        history_sets = set(df["white_set"])
        if g.get("bonus_n"):
            bonus_freq = Counter(df["Bonus"])
            full_combo_set = set(zip(df["white_set"], df["Bonus"]))
        else:
            full_combo_set = set(history_sets)
    elif g["kind"] == "digit":
        digit_freq = Counter(df[[f"D{i + 1}" for i in range(g["d"])]].to_numpy().ravel())
    else:
        pop_freq = Counter(df["Pop"])

tab_gen, tab_picks, tab_freq, tab_check, tab_odds = st.tabs(
    [
        "🎲 Number Generators",
        "💾 My Picks",
        "📊 Frequency Analysis",
        "🔍 Check My Numbers",
        "🧮 Odds & Expected Value",
    ]
)


def history_flags(pick: dict) -> list[str]:
    if df is None:
        return ["no history file loaded — upload one in the sidebar to enable history checks"]
    if "whites" in pick:
        ws = frozenset(pick["whites"])
        if "bonus" in pick and (ws, pick["bonus"]) in full_combo_set:
            return ["exact combo (mains + bonus) has hit the jackpot in your file ⚠️"]
        if ws in history_sets:
            return [f"{g['k']}-ball set has appeared before (different bonus or no bonus) ⚠️"]
        return [f"{g['k']}-ball set **never drawn** in your file ✅"]
    if "digits" in pick:
        s = "".join(map(str, pick["digits"]))
        hits = int((df["digit_str"] == s).sum())
        box = int((df["digit_sorted"] == "".join(sorted(s))).sum())
        return [
            f"drawn straight **{hits}×**, box **{box}×** in your file "
            f"(with only {10 ** g['d']:,} combos, repeats are routine)"
        ]
    return [f"popped **{pop_freq.get(pick['pop'], 0)}×** in your file"]


def render_pick(
    pick: dict,
    source: str,
    intention: str | None = None,
    attempts: int | None = None,
) -> None:
    record = {
        "#": len(st.session_state.picks) + 1,
        "Generated At": pd.Timestamp.now().strftime("%m/%d/%Y %I:%M:%S %p"),
        "Game": game_name,
        "Numbers": format_pick_plain(pick),
        "Source": source,
        "Intention": intention or "",
    }
    st.session_state.picks.append(record)
    st.session_state.last_pick = {
        "game": game_name,
        "pick": pick,
        "source": source,
        "intention": intention,
        "attempts": attempts,
    }
    st.toast("Pick saved to 💾 My Picks", icon="💾")


def show_last_pick() -> None:
    last = st.session_state.last_pick
    if not last or last.get("game") != game_name:
        return
    pick = last["pick"]
    st.markdown(f"### {format_pick_markdown(pick, g.get('bonus_name'))}")
    bits = [f"Source: **{last['source']}**"]
    if last.get("attempts"):
        bits.append(f"attempts to find never-drawn set: {last['attempts']}")
    bits += history_flags(pick)
    if last.get("intention"):
        bits.append(f"intention: *{last['intention']}*")
    st.caption(" · ".join(bits))


with tab_gen:
    show_last_pick()
    st.markdown("---")
    st.subheader("🧿 Intention Generator (Randonautica mode)")
    st.caption(
        "Your intention is SHA-256 hashed and XOR-mixed with quantum bytes fetched the moment "
        "you commit — output depends on both. (No physics evidence intention steers quantum "
        "outcomes; the distribution stays perfectly uniform. Great ritual though.)"
    )
    ic1, ic2 = st.columns([3, 1])
    intention = ic1.text_input(
        "Your intention",
        placeholder="e.g., abundance for my family",
        label_visibility="collapsed",
        key=f"intention_{gkey}",
    )
    if ic2.button("🧿 Commit intention", type="primary", width="stretch", key=f"btn_int_{gkey}"):
        if not intention.strip():
            st.warning("Set an intention first — even one word.")
        else:
            pick, src = generate(game_name, "intention", intention=intention, api_key=_anu_key())
            render_pick(pick, src, intention=intention.strip())
            st.rerun()
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("⚛️ Quantum pick")
        if st.button("Generate quantum numbers", type="primary", key=f"btn_q_{gkey}"):
            pick, src = generate(game_name, "quantum", api_key=_anu_key())
            render_pick(pick, src)
            st.rerun()

        st.subheader("🛡️ Crypto-secure quick pick")
        if st.button("Generate secure pick", key=f"btn_sec_{gkey}"):
            pick, src = generate(game_name, "secure", api_key=_anu_key())
            render_pick(pick, src)
            st.rerun()

        if g["kind"] == "matrix":
            st.subheader("🆕 Guaranteed never-drawn set")
            if df is None:
                st.caption("Upload a history file to enable.")
            else:
                st.caption(
                    "Regenerates until the main-ball set has zero appearances in your file. "
                    "Fun filter, not an edge."
                )
                if st.button("Generate virgin combination", key=f"btn_virgin_{gkey}"):
                    pick, src, tries = never_drawn_pick(
                        game_name, history_sets, api_key=_anu_key()
                    )
                    render_pick(pick, src, attempts=tries)
                    st.rerun()
        else:
            st.subheader("🆕 Never-drawn?")
            st.caption(
                f"Not offered for {game_name}: with so few possible outcomes, everything has "
                "been drawn many times — the generators above report how often instead."
            )

    with c2:
        if g["kind"] == "matrix" and g["n"] > 40:
            st.subheader("💰 Anti-popularity pick (the honest edge)")
            st.caption(
                "Main balls > 31 to dodge birthday pickers. Doesn't change win odds, but a "
                "shared-jackpot game pays you more when fewer co-winners split it."
            )
            if st.button("Generate anti-popularity pick", key=f"btn_anti_{gkey}"):
                pick, src = generate(game_name, "anti", api_key=_anu_key())
                render_pick(pick, src)
                st.rerun()
        elif g["kind"] == "digit":
            st.subheader("💰 Anti-popularity?")
            st.caption(
                "Pick 3/4 prizes are fixed per ticket — no sharing — so unpopular numbers "
                "carry zero benefit here. (In pari-mutuel digit states they would; not SC.)"
            )
        else:
            st.subheader("💰 Anti-popularity?")
            st.caption("CASH POP prizes are assigned at purchase — number popularity is irrelevant.")

        freq_for_game = (
            white_freq if g["kind"] == "matrix" else digit_freq if g["kind"] == "digit" else pop_freq
        )
        st.subheader("🔥 Hot pick")
        if df is None or not freq_for_game:
            st.caption("Upload a history file to enable hot/cold picks.")
        else:
            st.caption("Sampled from the most-drawn numbers. Entertainment — streaks don't persist.")
            if st.button("Generate hot pick", key=f"btn_hot_{gkey}"):
                if g["kind"] == "pop":
                    render_pick({"pop": freq_for_game.most_common(1)[0][0]}, "Most-drawn CASH POP number")
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="hot")
                    render_pick(pick, src)
                st.rerun()

            st.subheader("🧊 Cold pick")
            st.caption("Least-drawn numbers. 'Due' is the gambler's fallacy — equally (in)effective.")
            if st.button("Generate cold pick", key=f"btn_cold_{gkey}"):
                if g["kind"] == "pop":
                    ranked = [n for n, _ in freq_for_game.most_common()]
                    ranked += [n for n in range(1, g["n"] + 1) if n not in ranked]
                    render_pick({"pop": ranked[-1]}, "Least-drawn CASH POP number")
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="cold")
                    render_pick(pick, src)
                st.rerun()

with tab_picks:
    st.subheader("💾 Every number you've generated this session — all games")
    if not st.session_state.picks:
        st.info("No picks yet — every pick from any game is saved here automatically.")
    else:
        picks_df = pd.DataFrame(st.session_state.picks)
        st.dataframe(picks_df, hide_index=True, width="stretch")
        d1, d2, d3 = st.columns([1, 1, 2])
        d1.download_button(
            "⬇️ Download picks CSV",
            picks_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"my_sc_lottery_picks_{date.today():%Y%m%d}.csv",
            mime="text/csv",
            type="primary",
            key="dl_picks",
        )
        if d2.button("🗑️ Clear all picks", key="clear_picks"):
            st.session_state.picks = []
            st.session_state.last_pick = None
            st.rerun()
        d3.caption(f"{len(picks_df)} pick(s). Session-based — download before closing the tab.")

with tab_freq:
    if df is None or df.empty:
        st.info(
            f"No history loaded for {game_name}. Upload a CSV in the sidebar "
            "(date column + winning-numbers column) to unlock frequency analysis."
        )
    else:
        if g["kind"] == "matrix" and g.get("era_start") is not None:
            options = ["Current rules era", "All draws in file"]
            if g.get("white70_start") is not None:
                options.insert(1, "White balls 1–70 era (since Oct 2017)")
            era_choice = st.radio(
                "History window",
                options,
                index=0,
                horizontal=True,
                key=f"era_{gkey}",
            )
            if era_choice.startswith("Current"):
                dfe = df[df["Draw Date"] >= g["era_start"]]
            elif era_choice.startswith("White"):
                dfe = df[df["Draw Date"] >= g["white70_start"]]
            else:
                dfe = df
            if dfe.empty:
                st.warning("No draws in that window — showing the full file instead.")
                dfe = df
        else:
            dfe = df

        c1, c2 = st.columns(2)
        c1.metric("Draws analyzed", f"{len(dfe):,}")
        c2.metric(
            "Date range",
            f"{dfe['Draw Date'].min():%b %Y} – {dfe['Draw Date'].max():%b %Y}",
        )

        if g["kind"] == "matrix":
            wf_c = Counter(dfe[[f"W{i + 1}" for i in range(g["k"])]].to_numpy().ravel())
            wf = pd.DataFrame(
                {
                    "Number": range(1, g["n"] + 1),
                    "Times Drawn": [wf_c.get(x, 0) for x in range(1, g["n"] + 1)],
                }
            )
            st.subheader(f"Main balls (1–{g['n']})")
            st.caption(
                f"Uniform expectation: {len(dfe) * g['k'] / g['n']:.1f} per number — "
                "deviations are normal sampling noise."
            )
            st.bar_chart(wf.set_index("Number"))
            h1, h2 = st.columns(2)
            h1.markdown("**🔥 Hottest 10**")
            h1.dataframe(wf.nlargest(10, "Times Drawn"), hide_index=True, width="stretch")
            h2.markdown("**🧊 Coldest 10**")
            h2.dataframe(wf.nsmallest(10, "Times Drawn"), hide_index=True, width="stretch")
            if g.get("bonus_n"):
                bf_c = Counter(dfe["Bonus"])
                bonus_hi = g["bonus_n"]
                extra = [int(x) for x in bf_c if int(x) > bonus_hi]
                st.subheader(f"{g['bonus_name']} (1–{bonus_hi} under current rules)")
                if extra:
                    st.caption(
                        f"{len(extra)} historical bonus values sit above {bonus_hi} "
                        "(older matrices) and are omitted from this chart."
                    )
                bf = pd.DataFrame(
                    {
                        "Number": range(1, bonus_hi + 1),
                        "Times Drawn": [bf_c.get(x, 0) for x in range(1, bonus_hi + 1)],
                    }
                )
                st.bar_chart(bf.set_index("Number"))

        elif g["kind"] == "digit":
            pos_freq = Counter(dfe[[f"D{i + 1}" for i in range(g["d"])]].to_numpy().ravel())
            st.subheader("Digit frequency — overall")
            odf = pd.DataFrame(
                {"Digit": range(10), "Times Drawn": [pos_freq.get(x, 0) for x in range(10)]}
            )
            st.bar_chart(odf.set_index("Digit"))
            st.subheader("Digit frequency — by position")
            pos_cols = st.columns(g["d"])
            for i in range(g["d"]):
                pc = Counter(dfe[f"D{i + 1}"])
                with pos_cols[i]:
                    st.markdown(f"**Position {i + 1}**")
                    st.dataframe(
                        pd.DataFrame({"Digit": range(10), "×": [pc.get(x, 0) for x in range(10)]}),
                        hide_index=True,
                        width="stretch",
                        height=240,
                    )
            st.subheader("Most repeated straight combos")
            top = dfe["digit_str"].value_counts()
            t1, t2 = st.columns(2)
            t1.markdown("**Most repeated**")
            t1.dataframe(
                top.head(10).rename_axis("Combo").reset_index(name="Times"),
                hide_index=True,
                width="stretch",
            )
            t2.metric("Distinct combos seen", f"{dfe['digit_str'].nunique():,} of {10 ** g['d']:,}")

        else:
            pop_c = Counter(dfe["Pop"])
            st.subheader("CASH POP number frequency (1–15)")
            pf = pd.DataFrame(
                {"Number": range(1, 16), "Times Drawn": [pop_c.get(x, 0) for x in range(1, 16)]}
            )
            st.bar_chart(pf.set_index("Number"))
            st.caption(f"Uniform expectation: {len(dfe) / 15:.1f} per number.")

with tab_check:
    st.subheader(f"Check numbers against {game_name} history")
    if df is None or df.empty:
        st.info("Upload a history CSV in the sidebar to enable checking.")
    elif g["kind"] == "matrix":
        cols = st.columns(g["k"] + (1 if g.get("bonus_n") else 0))
        whites_in = [
            int(
                cols[i].number_input(
                    f"Ball {i + 1}",
                    min_value=1,
                    max_value=int(g["n"]),
                    value=min(7 * (i + 1), int(g["n"])),
                    step=1,
                    key=f"cw_{gkey}_{i}",
                )
            )
            for i in range(g["k"])
        ]
        bonus_in = (
            int(
                cols[-1].number_input(
                    g["bonus_name"],
                    min_value=1,
                    max_value=int(g["bonus_n"]),
                    value=7,
                    step=1,
                    key=f"cb_{gkey}",
                )
            )
            if g.get("bonus_n")
            else None
        )
        if st.button("Check history", type="primary", key=f"check_{gkey}"):
            if len(set(whites_in)) != g["k"]:
                st.error("Main balls must all be different.")
            else:
                ws = frozenset(whites_in)
                five = df[df["white_set"] == ws]
                if g.get("bonus_n"):
                    exact = five[five["Bonus"] == bonus_in]
                    if len(exact):
                        st.error(
                            f"😱 Exact combo hit the JACKPOT on {exact.iloc[0]['Draw Date']:%m/%d/%Y}."
                        )
                    elif len(five):
                        st.warning(
                            f"The {g['k']} main balls hit together on "
                            f"{five.iloc[0]['Draw Date']:%m/%d/%Y} (different {g['bonus_name']})."
                        )
                    else:
                        st.success("✅ Never drawn in your file.")
                elif len(five):
                    st.error(f"😱 This set won the JACKPOT on {five.iloc[0]['Draw Date']:%m/%d/%Y}.")
                else:
                    st.success("✅ Never drawn in your file.")

                rows = []
                for _, r in df.iterrows():
                    wm = len(ws & r["white_set"])
                    bm = (bonus_in == r["Bonus"]) if g.get("bonus_n") else None
                    label = next(
                        (
                            t[3]
                            for t in g["tiers"]
                            if t[0] == wm and (t[1] is None or t[1] == bm)
                        ),
                        None,
                    )
                    if label:
                        rows.append(
                            {
                                "Draw Date": r["Draw Date"].date(),
                                "Matched": f"{wm}" + (f" + {g['bonus_name']}" if bm else ""),
                                "Tier": label,
                            }
                        )
                if rows:
                    st.markdown(f"**Draws where these numbers would have won: {len(rows)}**")
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                else:
                    st.info("These numbers would never have won any tier in the file.")

    elif g["kind"] == "digit":
        cols = st.columns(g["d"])
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
            for i in range(g["d"])
        ]
        if st.button("Check history", type="primary", key=f"check_{gkey}"):
            s = "".join(map(str, digs))
            straight = df[df["digit_str"] == s]
            box = df[df["digit_sorted"] == "".join(sorted(s))]
            m1, m2, m3 = st.columns(3)
            m1.metric("Straight hits", len(straight))
            m2.metric("Box hits", len(box))
            m3.metric("Box type", f"{digit_box_ways(digs)}-way")
            if len(box):
                st.dataframe(
                    box[["Draw Date", "digit_str"]]
                    .head(25)
                    .rename(columns={"digit_str": "Drawn"}),
                    hide_index=True,
                    width="stretch",
                )
    else:
        pop_in = int(
            st.number_input(
                "Your CASH POP number",
                min_value=1,
                max_value=15,
                value=7,
                step=1,
                key=f"cp_{gkey}",
            )
        )
        if st.button("Check history", type="primary", key=f"check_{gkey}"):
            hits = df[df["Pop"] == pop_in]
            st.metric(
                f"Number {pop_in} popped",
                f"{len(hits)}× in {len(df)} drawings",
                delta=f"expected {len(df) / 15:.1f}",
            )

with tab_odds:
    st.subheader(f"{game_name} — exact odds & expected value")

    if g["kind"] == "matrix":
        n, k = g["n"], g["k"]
        if g.get("bonus_n"):
            st.latex(
                r"P(\text{exactly } k \text{ whites}) = "
                r"\frac{\binom{" + str(k) + r"}{k_{\mathrm{hit}}}\binom{" + str(n - k) + r"}{"
                + str(k) + r"-k_{\mathrm{hit}}}}{\binom{" + str(n) + r"}{" + str(k) + r"}}"
                r"\times P(\text{bonus})"
            )
        else:
            st.latex(
                r"P(\text{exactly } m \text{ of }" + rf" {k}) = "
                r"\frac{\binom{" + str(k) + r"}{m}\binom{" + str(n - k) + r"}{"
                + str(k) + r"-m}}{\binom{" + str(n) + r"}{" + str(k) + r"}}"
            )

        jc1, jc2 = st.columns(2)
        jackpot = jc1.number_input(
            "Jackpot CASH value ($)",
            min_value=10_000,
            value=int(g["default_jackpot"]),
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
            if g.get("sharing")
            else 1.0
        )

        em = expected_multiplier(g.get("multipliers"))
        with st.expander("✏️ Edit non-jackpot base prize amounts"):
            st.caption("These are official base (pre-multiplier) prizes. Verify against the current rules PDF.")
            for idx, (_km, _bm, prize, label) in enumerate(g["tiers"]):
                if prize is not None:
                    pkey = f"prize_{gkey}_{idx}"
                    if pkey not in st.session_state:
                        st.session_state[pkey] = int(prize)
                    st.number_input(label, min_value=0, step=1, key=pkey)

        rows, ev = [], 0.0
        st.markdown("**Prize table**")
        for idx, (km, bm, prize, label) in enumerate(g["tiers"]):
            p = matrix_tier_probability(g, km, bm)
            if prize is None:
                val = jackpot / max(co, 1.0)
                shown = "JACKPOT"
                avg_prize = val
                mult = 1.0
            else:
                val = float(st.session_state.get(f"prize_{gkey}_{idx}", prize))
                shown = f"{val:,.0f}"
                mult = em
                avg_prize = val * mult
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

        any_p = any_prize_probability(g)
        e1, e2, e3 = st.columns(3)
        e1.metric("Any prize", f"1 in {1 / any_p:.2f}")
        e2.metric(f"EV per ${g['price']:.0f} ticket", f"${ev:.2f}")
        e3.metric(
            "Expected loss per ticket",
            f"${g['price'] - ev:.2f}",
            delta=f"{(ev / g['price'] - 1) * 100:.0f}% return",
            delta_color="inverse",
        )
        if em > 1.01:
            st.caption(
                f"Non-jackpot prizes include the built-in multiplier "
                f"(expected {em:.2f}×). Jackpot is never multiplied."
            )
        official = g.get("official_any_odds")
        if official:
            st.caption(f"Published overall odds: 1 in {official:g}. Computed: 1 in {1 / any_p:.2f}.")

    elif g["kind"] == "digit":
        st.markdown("Enter the digits you'd play — box odds depend on repeats:")
        cols = st.columns(g["d"])
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
            for i in range(g["d"])
        ]
        ways = digit_box_ways(digs)
        total = 10 ** g["d"]
        with st.expander("✏️ Edit payouts"):
            skey, bkey = f"pay_{gkey}_straight", f"pay_{gkey}_box"
            if skey not in st.session_state:
                st.session_state[skey] = int(g["plays"]["Straight"])
            st.number_input("Straight payout", min_value=0, step=1, key=skey)
            if ways > 1:
                default_box = g["plays"].get(
                    f"Box ({ways}-way)",
                    round(g["plays"]["Straight"] / ways / 5) * 5,
                )
                if bkey not in st.session_state:
                    st.session_state[bkey] = int(default_box)
                st.number_input("Box payout", min_value=0, step=1, key=bkey)

        st.markdown("**Play types for your digits**")
        straight_pay = float(st.session_state.get(f"pay_{gkey}_straight", g["plays"]["Straight"]))
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
                    g["plays"].get(box_label, round(straight_pay / ways / 5) * 5),
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
            rows.append(
                {
                    "Play": "Box",
                    "Odds": "n/a — all digits identical (straight only)",
                    "Payout per $1": "—",
                    "EV per $1": "—",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "FIREBALL (doubles your wager) adds a drawn digit that can substitute for any one "
            f"drawn digit, creating extra winning combos at reduced payouts — official odds run "
            f"{'1 in 37 to 1 in 10,000' if g['d'] == 3 else '1 in 149 to 1 in 100,000'}. "
            "FIREBALL roughly preserves the game's payout percentage — it buys more chances, "
            "not better ones."
        )

    else:
        st.markdown(
            "- **Odds of winning: exactly 1 in 15** — one number is drawn; you win if it's yours.\n"
            "- Your prize is **randomly assigned at purchase** ($1 play: $5–$100; larger wagers scale "
            "to a $2,500 cap), so EV depends on the hidden prize distribution SCEL assigns — it is "
            "not publicly specified per ticket.\n"
            "- **Cover-all math:** buying all 15 numbers guarantees a win, cost 15× your per-number "
            "wager — profitable only if the assigned prize on the winning number exceeds your total "
            "outlay, which the prize distribution is designed to prevent on average.\n"
            "- No sharing, no popularity effects, no history dependence: the purest 1-in-15 coin toss "
            "in the lineup."
        )
        st.metric("Win probability", "1 in 15 (6.67%)")

st.markdown(
    '<div class="aiu-footer">Built by '
    '<a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">AI Upscale LLC</a>'
    " · Columbia, SC · For entertainment and education — play responsibly · "
    '<a href="https://www.sceducationlottery.com/PlayResponsibly" target="_blank" rel="noopener">'
    "Play Responsibly SC</a></div>",
    unsafe_allow_html=True,
)
