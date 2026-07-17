"""
MEGA MILLIONS ANALYSIS LAB
==========================
Frequency analysis | History checker | Quantum & secure RNG picks |
Never-drawn-combo generator | Exact odds & expected-value calculator

Current rules (since April 8, 2025):
  - 5 white balls from 1-70
  - 1 Mega Ball from 1-24
  - Ticket: $5 (multiplier included)
  - Jackpot odds: 1 in 290,472,336

Run:  streamlit run mega_millions_lab.py
"""

import hashlib
import io
import math
import secrets
from collections import Counter
from datetime import date

import pandas as pd
import requests
import streamlit as st

# ----------------------------------------------------------------------------
# CONSTANTS — current Mega Millions matrix
# ----------------------------------------------------------------------------
WHITE_MIN, WHITE_MAX = 1, 70
MEGA_MIN, MEGA_MAX = 1, 24
CURRENT_ERA_START = pd.Timestamp("2025-04-08")   # $5 ticket, MB 1-24
WHITE70_ERA_START = pd.Timestamp("2017-10-31")   # white balls became 1-70

TOTAL_COMBOS = math.comb(70, 5) * 24             # 290,472,336

# Prize tiers: (whites matched, mega matched, base prize, label)
# Jackpot prize handled separately.
TIERS = [
    (5, True,  None,      "JACKPOT"),
    (5, False, 2_000_000, "Match 5"),
    (4, True,  20_000,    "Match 4 + MB"),
    (4, False, 1_000,     "Match 4"),
    (3, True,  400,       "Match 3 + MB"),
    (3, False, 20,        "Match 3"),
    (2, True,  20,        "Match 2 + MB"),
    (1, True,  14,        "Match 1 + MB"),
    (0, True,  10,        "Mega Ball only"),
]

MULTIPLIERS = {2: 1/2.13, 3: 1/3.2, 4: 1/8, 5: 1/16, 10: 1/32}

# ----------------------------------------------------------------------------
# EXACT ODDS (hypergeometric)
# ----------------------------------------------------------------------------
def tier_probability(k_white: int, mega: bool) -> float:
    """Exact probability of matching exactly k white balls (of 5) and
    matching / not matching the Mega Ball, under current rules."""
    ways_white = math.comb(5, k_white) * math.comb(70 - 5, 5 - k_white)
    p_white = ways_white / math.comb(70, 5)
    p_mega = (1 / 24) if mega else (23 / 24)
    return p_white * p_mega


def expected_multiplier() -> float:
    return sum(m * p for m, p in MULTIPLIERS.items())


def expected_value(jackpot_cash: float, expected_cowinners_share: float = 1.0) -> dict:
    """EV of one $5 ticket. Non-jackpot prizes are multiplied (multiplier is
    included in the $5 ticket). Jackpot is divided by expected number of
    winners sharing it."""
    em = expected_multiplier()
    rows, ev = [], 0.0
    for k, mb, prize, label in TIERS:
        p = tier_probability(k, mb)
        if prize is None:
            contrib = p * (jackpot_cash / max(expected_cowinners_share, 1.0))
            rows.append((label, p, f"1 in {round(1/p):,}", jackpot_cash, contrib))
        else:
            contrib = p * prize * em
            rows.append((label, p, f"1 in {round(1/p):,}", prize, contrib))
        ev += contrib
    return {"rows": rows, "ev": ev, "expected_multiplier": em}

# ----------------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------------
@st.cache_data
def load_history(file_bytes: bytes | None) -> pd.DataFrame:
    if file_bytes:
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv("export.csv")   # preloaded historical file
    df["Draw Date"] = pd.to_datetime(df["Draw Date"])
    whites = df["Winning Numbers"].str.split(expand=True).astype(int)
    for i in range(5):
        df[f"W{i+1}"] = whites[i]
    df["white_set"] = whites.apply(frozenset, axis=1)
    df = df.sort_values("Draw Date", ascending=False).reset_index(drop=True)
    return df


def filter_era(df: pd.DataFrame, era: str) -> pd.DataFrame:
    if era == "Current rules (Apr 2025 → now)":
        return df[df["Draw Date"] >= CURRENT_ERA_START]
    if era == "White-ball 1-70 era (Oct 2017 → now)":
        return df[df["Draw Date"] >= WHITE70_ERA_START]
    return df

# ----------------------------------------------------------------------------
# GENERATORS
# ----------------------------------------------------------------------------
def secure_pick() -> tuple[list[int], int]:
    """Cryptographically secure quick pick (Python `secrets`)."""
    whites = sorted(secrets.SystemRandom().sample(range(WHITE_MIN, WHITE_MAX + 1), 5))
    mega = secrets.randbelow(MEGA_MAX) + 1
    return whites, mega


def quantum_pick() -> tuple[list[int], int, str]:
    """Randonautica-style pick using the ANU Quantum RNG (vacuum-fluctuation
    photonics). Falls back to crypto-secure randomness if the API is
    unreachable. Uses rejection sampling to keep the distribution uniform."""
    try:
        r = requests.get(
            "https://qrng.anu.edu.au/API/jsonI.php",
            params={"length": 64, "type": "uint8"},
            timeout=6,
        )
        r.raise_for_status()
        data = r.json()["data"]
        pool = list(data)

        def draw(n: int) -> int:
            # rejection sampling: uniform 0..n-1 from bytes
            limit = 256 - (256 % n)
            while pool:
                b = pool.pop()
                if b < limit:
                    return b % n
            raise RuntimeError("quantum pool exhausted")

        whites: set[int] = set()
        while len(whites) < 5:
            whites.add(draw(70) + 1)
        mega = draw(24) + 1
        return sorted(whites), mega, "ANU Quantum RNG (live)"
    except Exception:
        w, m = secure_pick()
        return w, m, "Quantum source unreachable — crypto-secure fallback"


def intention_pick(intention: str) -> tuple[list[int], int, str]:
    """Randonautica-style intention generation. Your intention text is
    SHA-256 hashed and XOR-mixed with quantum bytes fetched at the moment
    you commit the intention — so the output deterministically depends on
    BOTH what you typed and the quantum state at that instant. (Honesty
    note: physics has no evidence intention steers quantum outcomes;
    the mixing keeps the distribution perfectly uniform either way.)"""
    seed = hashlib.sha256(intention.strip().lower().encode()).digest()
    src = "ANU Quantum RNG ⊕ intention hash"
    try:
        r = requests.get(
            "https://qrng.anu.edu.au/API/jsonI.php",
            params={"length": 64, "type": "uint8"},
            timeout=6,
        )
        r.raise_for_status()
        qbytes = bytes(r.json()["data"])
    except Exception:
        qbytes = secrets.token_bytes(64)
        src = "CSPRNG ⊕ intention hash (quantum source offline)"

    mixed = bytes(q ^ seed[i % 32] for i, q in enumerate(qbytes))
    # stretch the entropy pool so rejection sampling can't run dry
    pool = list(hashlib.sha512(mixed).digest() + hashlib.sha512(mixed[::-1]).digest() + mixed)

    def draw(n: int) -> int:
        limit = 256 - (256 % n)
        while pool:
            b = pool.pop()
            if b < limit:
                return b % n
        raise RuntimeError("entropy pool exhausted")

    whites: set[int] = set()
    while len(whites) < 5:
        whites.add(draw(70) + 1)
    mega = draw(24) + 1
    return sorted(whites), mega, src


def never_drawn_pick(history_sets: set[frozenset], generator) -> tuple[list[int], int, int]:
    """Generate until the 5-white-ball combination has never appeared in the
    historical file. (With ~2,500 draws out of 12.6M possible white-ball
    combos, this almost always succeeds on the first try.)"""
    attempts = 0
    while True:
        attempts += 1
        result = generator()
        whites, mega = result[0], result[1]
        if frozenset(whites) not in history_sets:
            return whites, mega, attempts


def anti_popularity_pick() -> tuple[list[int], int]:
    """All five white balls > 31 (outside the birthday range). Does NOT
    change win probability — but if you win, you're statistically less
    likely to split the jackpot with birthday-pickers."""
    rng = secrets.SystemRandom()
    whites = sorted(rng.sample(range(32, WHITE_MAX + 1), 5))
    mega = rng.randint(MEGA_MIN, MEGA_MAX)
    return whites, mega


def hot_cold_pick(freq: Counter, mega_freq: Counter, mode: str) -> tuple[list[int], int]:
    ranked = [n for n, _ in freq.most_common()]
    all_nums = list(range(WHITE_MIN, WHITE_MAX + 1))
    ranked += [n for n in all_nums if n not in ranked]      # never-drawn = coldest
    pool = ranked[:20] if mode == "hot" else ranked[-20:]
    whites = sorted(secrets.SystemRandom().sample(pool, 5))
    m_ranked = [n for n, _ in mega_freq.most_common()]
    m_ranked += [n for n in range(MEGA_MIN, MEGA_MAX + 1) if n not in m_ranked]
    m_pool = m_ranked[:8] if mode == "hot" else m_ranked[-8:]
    mega = secrets.choice(m_pool)
    return whites, mega

# ----------------------------------------------------------------------------
# HISTORY CHECKING
# ----------------------------------------------------------------------------
def check_against_history(df: pd.DataFrame, whites: list[int], mega: int) -> pd.DataFrame:
    ws = set(whites)
    out = []
    for _, row in df.iterrows():
        wm = len(ws & row["white_set"])
        mm = mega == row["Mega Ball"]
        if wm >= 3 or (wm >= 1 and mm) or mm and wm == 0:
            label = next((t[3] for t in TIERS if t[0] == wm and t[1] == mm), None)
            if label:
                out.append({
                    "Draw Date": row["Draw Date"].date(),
                    "Winning Numbers": row["Winning Numbers"],
                    "Mega Ball": row["Mega Ball"],
                    "Whites Matched": wm,
                    "MB Matched": "✓" if mm else "—",
                    "Would-Have-Won Tier": label,
                })
    return pd.DataFrame(out)

# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Mega Millions Analysis Lab | AI Upscale", page_icon="🎰", layout="wide")

# ---- AI Upscale "Midnight Warmth" branding ---------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap');

html, body, [class*="css"], .stMarkdown, p, li, label {
    font-family: 'Plus Jakarta Sans', sans-serif;
}
h1, h2, h3, h4, [data-testid="stMetricValue"] {
    font-family: 'Rajdhani', sans-serif !important;
    letter-spacing: 0.02em;
}
h1 { color: #F5A623 !important; }
h2, h3 { color: #F4EDE4 !important; }
[data-testid="stMetricValue"] { color: #F5A623 !important; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background: #13203A; border-radius: 8px 8px 0 0;
    font-family: 'Rajdhani', sans-serif; font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background: #F5A623 !important; color: #0A1220 !important;
}
.stButton > button {
    font-family: 'Rajdhani', sans-serif; font-weight: 600;
    border: 1px solid #F5A623;
}
.aiu-header {
    display: flex; align-items: center; gap: 18px;
    padding: 6px 0 14px 0; border-bottom: 1px solid #24365A;
    margin-bottom: 10px;
}
.aiu-header img { height: 52px; }
.aiu-footer {
    margin-top: 40px; padding-top: 14px; border-top: 1px solid #24365A;
    font-size: 0.85rem; color: #8FA3C8;
}
.aiu-footer a, .aiu-header a { color: inherit; text-decoration: none; }
.aiu-footer a:hover { color: #F5A623; }
</style>

<div class="aiu-header">
  <a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">
    <img src="https://aiupscalellc.netlify.app/logo.svg" alt="AI Upscale LLC">
  </a>
  <div>
    <div style="font-family:'Rajdhani',sans-serif;font-size:1.9rem;font-weight:700;color:#F5A623;line-height:1;">
      🎰 MEGA MILLIONS ANALYSIS LAB
    </div>
    <div style="color:#8FA3C8;font-size:0.9rem;">
      Frequency analytics · history checker · quantum picks · exact odds engine — an
      <a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener"
         style="color:inherit;text-decoration:none;">AI Upscale LLC</a> tool
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Data")
    up = st.file_uploader("Update history CSV (optional)", type="csv",
                          help="Same format as the megamillions export: Draw Date, Winning Numbers, Mega Ball, Multiplier")
    era = st.radio("Analysis era", [
        "Current rules (Apr 2025 → now)",
        "White-ball 1-70 era (Oct 2017 → now)",
        "All history (mixed rules — stats skewed)",
    ], index=1)
    st.divider()
    st.subheader("⚖️ Reality check")
    st.markdown(
        "Every combination has **exactly the same** 1-in-290,472,336 chance, "
        "every draw, regardless of history. Frequency patterns are noise, not "
        "signal — the balls have no memory. The one lever that changes your "
        "*expected payout* (not your win odds) is picking **unpopular** numbers "
        "so a jackpot is less likely to be split. Play for fun, with money you "
        "can afford to lose."
    )

try:
    df_all = load_history(up.getvalue() if up else None)
except FileNotFoundError:
    st.error("Place your export.csv next to this script, or upload it in the sidebar.")
    st.stop()

df = filter_era(df_all, era)
white_freq = Counter(df[[f"W{i+1}" for i in range(5)]].values.ravel())
mega_freq = Counter(df["Mega Ball"])
history_sets = set(df_all["white_set"])
full_combo_set = set(zip(df_all["white_set"], df_all["Mega Ball"]))

tab_freq, tab_gen, tab_check, tab_odds = st.tabs(
    ["📊 Frequency Analysis", "🎲 Number Generators", "🔍 Check My Numbers", "🧮 Odds & Expected Value"]
)

# --------------------------- FREQUENCY --------------------------------------
with tab_freq:
    c1, c2, c3 = st.columns(3)
    c1.metric("Draws analyzed", f"{len(df):,}")
    c2.metric("Date range", f"{df['Draw Date'].min():%b %Y} – {df['Draw Date'].max():%b %Y}")
    c3.metric("Unique white-ball combos possible", "12,103,014")

    wf = pd.DataFrame({
        "Number": range(WHITE_MIN, WHITE_MAX + 1),
        "Times Drawn": [white_freq.get(n, 0) for n in range(WHITE_MIN, WHITE_MAX + 1)],
    })
    expected = len(df) * 5 / 70
    st.subheader("White balls (1–70)")
    st.caption(f"Expected count per number if perfectly uniform: **{expected:.1f}** — "
               "deviations you see below are normal sampling noise.")
    st.bar_chart(wf.set_index("Number"))

    hot = wf.nlargest(10, "Times Drawn")
    cold = wf.nsmallest(10, "Times Drawn")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**🔥 Hottest 10 whites**")
        st.dataframe(hot, hide_index=True, use_container_width=True)
    with cc2:
        st.markdown("**🧊 Coldest 10 whites**")
        st.dataframe(cold, hide_index=True, use_container_width=True)

    st.subheader(f"Mega Ball ({MEGA_MIN}–{MEGA_MAX} under current rules)")
    mf = pd.DataFrame({
        "Number": range(MEGA_MIN, MEGA_MAX + 1),
        "Times Drawn": [mega_freq.get(n, 0) for n in range(MEGA_MIN, MEGA_MAX + 1)],
    })
    st.bar_chart(mf.set_index("Number"))

    st.subheader("Pattern stats (of drawn combos)")
    sums = df[[f"W{i+1}" for i in range(5)]].sum(axis=1)
    odd_counts = df[[f"W{i+1}" for i in range(5)]].apply(lambda r: sum(x % 2 for x in r), axis=1)
    p1, p2, p3 = st.columns(3)
    p1.metric("Avg white-ball sum", f"{sums.mean():.0f}", help="Typical winning sums cluster near the theoretical mean of 177.5 simply because more combinations exist there.")
    p2.metric("Most common odd/even split", f"{odd_counts.mode()[0]} odd / {5 - odd_counts.mode()[0]} even")
    p3.metric("Repeat 5-ball combos in history", f"{len(df_all) - len(history_sets):,}")

# --------------------------- GENERATORS -------------------------------------
with tab_gen:
    st.markdown("All generators follow official rules: **5 unique whites 1–70 + Mega Ball 1–24**, "
                "uniform via rejection sampling. Every pick is checked against your full history file.")

    def render_pick(whites, mega, source, attempts=None):
        balls = " ".join(f"`{w:02d}`" for w in whites)
        st.markdown(f"### {balls}  —  🟡 MB `{mega:02d}`")
        combo_seen = (frozenset(whites), mega) in full_combo_set
        whiteset_seen = frozenset(whites) in history_sets
        bits = [f"Source: **{source}**"]
        if attempts:
            bits.append(f"attempts to find never-drawn set: {attempts}")
        bits.append("5-ball set has appeared before ⚠️" if whiteset_seen
                    else "5-ball set **never drawn** in your file ✅")
        bits.append("full 6-number combo previously won the jackpot(!)" if combo_seen
                    else "full combo never drawn ✅")
        st.caption(" · ".join(bits))

    st.markdown("---")
    st.subheader("🧿 Intention Generator (full Randonautica mode)")
    st.caption(
        "Type your intention, take a breath, and commit. Your intention is SHA-256 hashed and "
        "XOR-mixed with quantum bytes pulled **at the exact moment you press the button** — the "
        "numbers literally depend on both what you wrote and the quantum state of that instant. "
        "(Straight talk: there's no evidence intention biases quantum outcomes, and the mix stays "
        "perfectly uniform — but as a ritual for choosing numbers, nothing beats it.)"
    )
    ic1, ic2 = st.columns([3, 1])
    intention = ic1.text_input("Your intention", placeholder="e.g., abundance for my family",
                               label_visibility="collapsed")
    if ic2.button("🧿 Commit intention", type="primary", use_container_width=True):
        if not intention.strip():
            st.warning("Set an intention first — even one word.")
        else:
            w, m, src = intention_pick(intention)
            render_pick(w, m, src)
            st.caption(f'Intention: *"{intention.strip()}"* — same intention + different quantum moment = different numbers.')
    st.markdown("---")

    g1, g2 = st.columns(2)
    with g1:
        st.subheader("⚛️ Quantum pick (Randonautica-style)")
        st.caption("Live quantum vacuum-fluctuation randomness from the ANU QRNG. "
                   "Falls back to crypto-secure RNG if the API is offline.")
        if st.button("Generate quantum numbers", type="primary"):
            w, m, src = quantum_pick()
            render_pick(w, m, src)

        st.subheader("🛡️ Crypto-secure quick pick")
        if st.button("Generate secure pick"):
            w, m = secure_pick()
            render_pick(w, m, "Python `secrets` CSPRNG")

        st.subheader("🆕 Guaranteed never-drawn set")
        st.caption("Regenerates until the 5-white-ball set has zero appearances in your file. "
                   "(This is a fun filter, not an edge — never-drawn combos win at the same rate as any other.)")
        if st.button("Generate virgin combination"):
            w, m, tries = never_drawn_pick(history_sets, secure_pick)
            render_pick(w, m, "CSPRNG + history filter", attempts=tries)

    with g2:
        st.subheader("💰 Anti-popularity pick (the honest edge)")
        st.caption("All whites > 31 to dodge the birthday crowd. Doesn't change win odds — "
                   "but a winning ticket is less likely to be **shared**, which raises expected payout. "
                   "This is the only pick strategy with genuine mathematical support.")
        if st.button("Generate anti-popularity pick"):
            w, m = anti_popularity_pick()
            render_pick(w, m, "CSPRNG, whites restricted to 32–70")

        st.subheader("🔥 Hot-numbers pick")
        st.caption("Sampled from the 20 most-drawn whites and 8 most-drawn Mega Balls in the selected era. For entertainment — hot streaks don't persist.")
        if st.button("Generate hot pick"):
            w, m = hot_cold_pick(white_freq, mega_freq, "hot")
            render_pick(w, m, "Frequency-weighted (hot)")

        st.subheader("🧊 Cold-numbers pick")
        st.caption("Sampled from the least-drawn numbers. Equally (in)effective — 'due' numbers are the gambler's fallacy.")
        if st.button("Generate cold pick"):
            w, m = hot_cold_pick(white_freq, mega_freq, "cold")
            render_pick(w, m, "Frequency-weighted (cold)")

# --------------------------- CHECKER ----------------------------------------
with tab_check:
    st.subheader("Check numbers against full drawing history")
    cols = st.columns(6)
    whites_in = []
    for i in range(5):
        whites_in.append(cols[i].number_input(f"White {i+1}", WHITE_MIN, WHITE_MAX, value=[7, 14, 21, 42, 63][i], key=f"w{i}"))
    mega_in = cols[5].number_input("Mega Ball", MEGA_MIN, MEGA_MAX, value=7)

    if st.button("Check history", type="primary"):
        if len(set(whites_in)) != 5:
            st.error("White balls must be five different numbers.")
        else:
            ws = frozenset(int(x) for x in whites_in)
            exact = df_all[(df_all["white_set"] == ws) & (df_all["Mega Ball"] == mega_in)]
            fiveball = df_all[df_all["white_set"] == ws]
            if len(exact):
                st.error(f"😱 This exact 6-number combo WON the jackpot on {exact.iloc[0]['Draw Date']:%m/%d/%Y}.")
            elif len(fiveball):
                st.warning(f"The 5 white balls hit together on {fiveball.iloc[0]['Draw Date']:%m/%d/%Y} (different Mega Ball).")
            else:
                st.success("✅ This combination has never been drawn in your file.")

            matches = check_against_history(df_all, [int(x) for x in whites_in], int(mega_in))
            if len(matches):
                st.markdown(f"**Historical draws where these numbers would have won a prize: {len(matches)}**")
                st.dataframe(matches, hide_index=True, use_container_width=True)
            else:
                st.info("These numbers would never have won any prize tier in the file.")

        st.markdown("**Individual number history (selected era):**")
        hist_rows = [{"Ball": f"White {w}", "Times drawn": white_freq.get(int(w), 0)} for w in whites_in]
        hist_rows.append({"Ball": f"Mega {mega_in}", "Times drawn": mega_freq.get(int(mega_in), 0)})
        st.dataframe(pd.DataFrame(hist_rows), hide_index=True)

# --------------------------- ODDS -------------------------------------------
with tab_odds:
    st.subheader("Exact odds — every tier, computed from combinatorics")
    st.latex(r"P(k\text{ whites}) = \frac{\binom{5}{k}\binom{65}{5-k}}{\binom{70}{5}}, \qquad P(\text{MB}) = \frac{1}{24}")

    jc1, jc2 = st.columns(2)
    jackpot_cash = jc1.number_input("Jackpot CASH value ($)", min_value=1_000_000,
                                    value=200_000_000, step=10_000_000, format="%d")
    co = jc2.number_input("Expected winners sharing jackpot", min_value=1.0, value=1.0, step=0.25,
                          help="Rises above 1 on huge, heavily-played jackpots. Anti-popularity picks push your personal value toward 1.")

    res = expected_value(float(jackpot_cash), co)
    odds_df = pd.DataFrame(res["rows"], columns=["Tier", "Probability", "Odds", "Base Prize ($)", "EV contribution ($)"])
    odds_df["Probability"] = odds_df["Probability"].map(lambda p: f"{p:.10f}")
    odds_df["EV contribution ($)"] = odds_df["EV contribution ($)"].map(lambda v: f"{v:.4f}")
    st.dataframe(odds_df, hide_index=True, use_container_width=True)

    any_prize = sum(tier_probability(k, m) for k, m, _, _ in TIERS)
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Any prize", f"1 in {1/any_prize:.1f}")
    e2.metric("Expected multiplier", f"{res['expected_multiplier']:.2f}×")
    e3.metric("EV per $5 ticket", f"${res['ev']:.2f}")
    e4.metric("Expected loss per ticket", f"${5 - res['ev']:.2f}",
              delta=f"{(res['ev']/5 - 1)*100:.0f}% return", delta_color="inverse")

    be = 5 / (res['ev'] / jackpot_cash) if jackpot_cash else 0
    st.markdown("---")
    st.markdown("#### 'Never drawn before' — does it help?")
    st.markdown(
        f"Your file contains **{len(full_combo_set):,}** previously drawn 6-number combos out of "
        f"**{TOTAL_COMBOS:,}** possible — that's **{len(full_combo_set)/TOTAL_COMBOS:.6%}** of the space. "
        "Filtering them out neither helps nor hurts: repeats are just as likely as any specific new combo. "
        "It's a preference, and the app supports it — with eyes open."
    )
    st.markdown("#### What actually moves the needle")
    st.markdown(
        "- **Nothing** changes the 1-in-290M jackpot odds except buying more tickets (linearly, at $5 each).\n"
        "- **Unpopular numbers** (whites > 31, avoiding sequences and 'lucky 7s') raise your *expected share* if you win.\n"
        "- **EV is positive only** when jackpot cash × your unshared share exceeds roughly $1.4B — and even then, "
        "variance means you'd need millions of lifetimes to realize it.\n"
        "- The house edge here (~40–75%) is far worse than any casino table game. Budget accordingly."
    )

st.markdown(
    '<div class="aiu-footer">Built by '
    '<a href="https://aiupscalellc.netlify.app/" target="_blank" rel="noopener">AI Upscale LLC</a>'
    ' · Columbia, SC · For entertainment and education — play responsibly.</div>',
    unsafe_allow_html=True,
)
