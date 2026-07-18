"""
SC LOTTERY ANALYSIS LAB — an AI Upscale LLC tool
=================================================
All six South Carolina Education Lottery terminal games:
  Mega Millions · Powerball · Palmetto Cash 5 · Pick 4 + FIREBALL ·
  Pick 3 + FIREBALL · CASH POP

Frequency analysis | History checker | Quantum / secure / intention picks |
Never-drawn combos | Exact odds & expected-value engine per game

Matrices verified against https://www.sceducationlottery.com/Games/Odds
Run:  streamlit run sc_lottery_lab.py
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

# ============================================================================
# GAME CONFIGURATION
# ============================================================================
# Matrix game tiers: (whites matched, bonus matched, default prize, label)
#   prize None = jackpot / rolling top prize.
# Digit games use play-type tables computed combinatorially.

GAMES = {
    "Mega Millions": dict(
        kind="matrix", k=5, n=70, bonus_n=24, bonus_name="Mega Ball",
        price=5.0, sharing=True, default_jackpot=200_000_000,
        tiers=[
            (5, True,  None,      "JACKPOT"),
            (5, False, 2_000_000, "Match 5"),
            (4, True,  20_000,    "Match 4 + MB"),
            (4, False, 1_000,     "Match 4"),
            (3, True,  400,       "Match 3 + MB"),
            (3, False, 20,        "Match 3"),
            (2, True,  20,        "Match 2 + MB"),
            (1, True,  14,        "Match 1 + MB"),
            (0, True,  10,        "Mega Ball only"),
        ],
        note="Built-in multiplier (2×–10×) included in the $5 ticket applies to non-jackpot prizes.",
        era_start=pd.Timestamp("2025-04-08"),
        preload="export.csv",
    ),
    "Powerball": dict(
        kind="matrix", k=5, n=69, bonus_n=26, bonus_name="Powerball",
        price=2.0, sharing=True, default_jackpot=250_000_000,
        tiers=[
            (5, True,  None,      "JACKPOT"),
            (5, False, 1_000_000, "Match 5"),
            (4, True,  50_000,    "Match 4 + PB"),
            (4, False, 100,       "Match 4"),
            (3, True,  100,       "Match 3 + PB"),
            (3, False, 7,         "Match 3"),
            (2, True,  7,         "Match 2 + PB"),
            (1, True,  4,         "Match 1 + PB"),
            (0, True,  4,         "Powerball only"),
        ],
        note="Power Play (extra $1) multiplies non-jackpot prizes; Match 5 with Power Play is always $2M.",
        era_start=pd.Timestamp("2015-10-07"),
    ),
    "Palmetto Cash 5": dict(
        kind="matrix", k=5, n=42, bonus_n=None, bonus_name=None,
        price=1.0, sharing="jackpot_only", default_jackpot=190_000,
        tiers=[
            (5, None, None, "JACKPOT"),
            (4, None, 300,  "Match 4"),
            (3, None, 10,   "Match 3"),
            (2, None, 1,    "Match 2"),
        ],
        note="SC-only game, drawn nightly. Power-Up add-on ($1) can multiply non-jackpot prizes. "
             "Verify prize amounts against the official rules PDF — they're editable below.",
        era_start=None,
    ),
    "Pick 4 + FIREBALL": dict(
        kind="digit", d=4, price=1.0, sharing=False,
        note="Digits 0–9, repeats allowed. FIREBALL (doubles wager) adds a drawn digit that can "
             "replace any one of the four. Official odds: 1 in 417 to 1 in 10,000 by play type; "
             "FIREBALL 1 in 149 to 1 in 100,000.",
        plays={  # play type: default $1-wager payout (verify vs official rules)
            "Straight": 5000, "Box (24-way)": 200, "Box (12-way)": 400,
            "Box (6-way)": 800, "Box (4-way)": 1198,
        },
    ),
    "Pick 3 + FIREBALL": dict(
        kind="digit", d=3, price=1.0, sharing=False,
        note="Digits 0–9, repeats allowed. FIREBALL (doubles wager) adds a drawn digit that can "
             "replace any one of the three. Official odds: 1 in 100 to 1 in 1,000 by play type; "
             "FIREBALL 1 in 37 to 1 in 10,000.",
        plays={"Straight": 500, "Box (6-way)": 80, "Box (3-way)": 160},
    ),
    "CASH POP": dict(
        kind="pop", n=15, price=1.0, sharing=False,
        note="Pick one number 1–15; one number drawn per drawing (Midday & Evening). Odds 1 in 15. "
             "Your prize amount is randomly assigned when you buy ($1 play pays $5–$100; higher "
             "wagers scale up to $2,500). You can also buy multiple/all numbers.",
    ),
}

# ============================================================================
# GENERIC ODDS MATH
# ============================================================================
def matrix_tier_probability(g: dict, k_match: int, bonus: bool | None) -> float:
    ways = math.comb(g["k"], k_match) * math.comb(g["n"] - g["k"], g["k"] - k_match)
    p = ways / math.comb(g["n"], g["k"])
    if g["bonus_n"]:
        p *= (1 / g["bonus_n"]) if bonus else ((g["bonus_n"] - 1) / g["bonus_n"])
    return p


def digit_box_ways(digits: list[int]) -> int:
    """Number of distinct arrangements of the chosen digits (box 'ways')."""
    c = Counter(digits)
    ways = math.factorial(len(digits))
    for v in c.values():
        ways //= math.factorial(v)
    return ways


MM_MULTIPLIERS = {2: 1/2.13, 3: 1/3.2, 4: 1/8, 5: 1/16, 10: 1/32}
mm_expected_multiplier = sum(m * p for m, p in MM_MULTIPLIERS.items())

# ============================================================================
# DATA LOADING — tolerant per-game history parser
# ============================================================================
@st.cache_data
def load_history(game_name: str, file_bytes: bytes | None) -> pd.DataFrame | None:
    g = GAMES[game_name]
    if file_bytes:
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif g.get("preload"):
        try:
            df = pd.read_csv(g["preload"])
        except FileNotFoundError:
            return None
    else:
        return None

    df.columns = [c.strip() for c in df.columns]
    date_col = next((c for c in df.columns if "date" in c.lower()), df.columns[0])
    df["Draw Date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["Draw Date"])

    num_col = next((c for c in df.columns if "winning" in c.lower() or "number" in c.lower()), None)

    if g["kind"] == "matrix":
        parts = df[num_col].astype(str).str.replace(r"[-,]", " ", regex=True).str.split()
        nums = pd.DataFrame(parts.tolist(), index=df.index).iloc[:, : g["k"]].astype(int)
        for i in range(g["k"]):
            df[f"W{i+1}"] = nums[i]
        df["white_set"] = nums.apply(frozenset, axis=1)
        if g["bonus_n"]:
            bcol = next((c for c in df.columns
                         if g["bonus_name"].lower().replace(" ", "") in c.lower().replace(" ", "")), None)
            df["Bonus"] = df[bcol].astype(int) if bcol else nums.iloc[:, -1]
    elif g["kind"] == "digit":
        parts = df[num_col].astype(str).str.replace(r"[-,]", " ", regex=True).str.split()
        nums = pd.DataFrame(parts.tolist(), index=df.index).iloc[:, : g["d"]].astype(int)
        for i in range(g["d"]):
            df[f"D{i+1}"] = nums[i]
        df["digit_str"] = nums.astype(str).agg("".join, axis=1)
        df["digit_sorted"] = df["digit_str"].apply(lambda s: "".join(sorted(s)))
    else:  # pop
        df["Pop"] = df[num_col].astype(int)

    return df.sort_values("Draw Date", ascending=False).reset_index(drop=True)

# ============================================================================
# GENERATORS — generic across games
# ============================================================================
def _quantum_bytes(n: int = 64) -> tuple[bytes, bool]:
    try:
        r = requests.get("https://qrng.anu.edu.au/API/jsonI.php",
                         params={"length": n, "type": "uint8"}, timeout=6)
        r.raise_for_status()
        return bytes(r.json()["data"]), True
    except Exception:
        return secrets.token_bytes(n), False


def _pool_sampler(pool_bytes: bytes):
    pool = list(hashlib.sha512(pool_bytes).digest()
                + hashlib.sha512(pool_bytes[::-1]).digest() + pool_bytes)

    def draw(n: int) -> int:
        limit = 256 - (256 % n)
        while pool:
            b = pool.pop()
            if b < limit:
                return b % n
        raise RuntimeError("entropy pool exhausted")
    return draw


def generate(game_name: str, method: str, intention: str = "",
             freq: Counter | None = None, mode: str = "hot") -> tuple[dict, str]:
    """Returns (pick dict, source label). Pick dict keys depend on game kind."""
    g = GAMES[game_name]
    rng = secrets.SystemRandom()

    if method in ("quantum", "intention"):
        qb, live = _quantum_bytes()
        if method == "intention":
            seed = hashlib.sha256(intention.strip().lower().encode()).digest()
            qb = bytes(q ^ seed[i % 32] for i, q in enumerate(qb))
            src = ("ANU Quantum RNG ⊕ intention hash" if live
                   else "CSPRNG ⊕ intention hash (quantum offline)")
        else:
            src = "ANU Quantum RNG (live)" if live else "Quantum offline — CSPRNG fallback"
        draw = _pool_sampler(qb)
    else:
        draw = lambda n: rng.randrange(n)
        src = {"secure": "Crypto-secure CSPRNG",
               "anti": "CSPRNG, birthday-range excluded",
               "hotcold": f"Frequency-weighted ({mode})"}.get(method, "CSPRNG")

    if g["kind"] == "matrix":
        lo = 32 if method == "anti" else 1
        pool_hi = g["n"]
        if method == "anti" and pool_hi - lo + 1 < g["k"]:
            lo = 1
        if method == "hotcold" and freq:
            ranked = [x for x, _ in freq.most_common()]
            ranked += [x for x in range(1, g["n"] + 1) if x not in ranked]
            cand = ranked[:20] if mode == "hot" else ranked[-20:]
            whites = sorted(rng.sample(cand, g["k"]))
        else:
            whites: set[int] = set()
            while len(whites) < g["k"]:
                whites.add(lo + draw(pool_hi - lo + 1))
            whites = sorted(whites)
        pick = {"whites": whites}
        if g["bonus_n"]:
            pick["bonus"] = 1 + draw(g["bonus_n"])
        return pick, src

    if g["kind"] == "digit":
        if method == "hotcold" and freq:
            ranked = [x for x, _ in freq.most_common()]
            ranked += [x for x in range(10) if x not in ranked]
            cand = ranked[:5] if mode == "hot" else ranked[-5:]
            digits = [rng.choice(cand) for _ in range(g["d"])]
        else:
            digits = [draw(10) for _ in range(g["d"])]
        return {"digits": digits, "fireball": draw(10)}, src

    # pop
    return {"pop": 1 + draw(g["n"])}, src

# ============================================================================
# UI SETUP + AI UPSCALE BRANDING
# ============================================================================
st.set_page_config(page_title="SC Lottery Analysis Lab | AI Upscale", page_icon="🎰", layout="wide")

st.markdown("""
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
""", unsafe_allow_html=True)

# ---- game selector ----------------------------------------------------------
game_name = st.selectbox("🎯 Select game", list(GAMES.keys()))
g = GAMES[game_name]
st.caption(g["note"])

with st.sidebar:
    st.header("Data")
    up = st.file_uploader(f"Upload {game_name} history CSV", type="csv",
                          help="Needs a date column and a winning-numbers column "
                               "(space/dash separated). Mega Millions history is preloaded.")
    st.divider()
    st.subheader("⚖️ Reality check")
    st.markdown(
        "Every combination in every draw game has identical odds, every draw — balls and "
        "digits have no memory. Frequency stats describe the past; they don't predict. "
        "Fixed-prize games (Pick 3/4, CASH POP) can't even benefit from unpopular numbers. "
        "Play for fun, with money you can afford to lose. "
        "[Play Responsibly SC](https://www.sceducationlottery.com/PlayResponsibly)"
    )

df = load_history(game_name, up.getvalue() if up else None)

# per-game derived stats
white_freq: Counter = Counter()
digit_freq: Counter = Counter()
pop_freq: Counter = Counter()
bonus_freq: Counter = Counter()
history_sets: set = set()
full_combo_set: set = set()
if df is not None:
    if g["kind"] == "matrix":
        white_freq = Counter(df[[f"W{i+1}" for i in range(g["k"])]].values.ravel())
        history_sets = set(df["white_set"])
        if g["bonus_n"]:
            bonus_freq = Counter(df["Bonus"])
            full_combo_set = set(zip(df["white_set"], df["Bonus"]))
        else:
            full_combo_set = history_sets
    elif g["kind"] == "digit":
        digit_freq = Counter(df[[f"D{i+1}" for i in range(g["d"])]].values.ravel())
    else:
        pop_freq = Counter(df["Pop"])

tab_gen, tab_picks, tab_freq, tab_check, tab_odds = st.tabs(
    ["🎲 Number Generators", "💾 My Picks", "📊 Frequency Analysis", "🔍 Check My Numbers", "🧮 Odds & Expected Value"]
)

# ============================================================================
# GENERATORS TAB
# ============================================================================
with tab_gen:
    if "picks" not in st.session_state:
        st.session_state.picks = []

    def fmt_pick(pick: dict) -> str:
        if "whites" in pick:
            s = " ".join(f"`{w:02d}`" for w in pick["whites"])
            if "bonus" in pick:
                s += f"  —  🟡 {g['bonus_name']} `{pick['bonus']:02d}`"
            return s
        if "digits" in pick:
            return " ".join(f"`{d}`" for d in pick["digits"]) + f"  —  🔥 FIREBALL `{pick['fireball']}`"
        return f"💥 `{pick['pop']}`"

    def pick_numbers_str(pick: dict) -> str:
        if "whites" in pick:
            s = " ".join(f"{w:02d}" for w in pick["whites"])
            return s + (f" + {pick['bonus']:02d}" if "bonus" in pick else "")
        if "digits" in pick:
            return "".join(map(str, pick["digits"])) + f" (FB {pick['fireball']})"
        return str(pick["pop"])

    def history_flags(pick: dict) -> list[str]:
        out = []
        if df is None:
            return ["no history file loaded for this game — upload one in the sidebar to enable history checks"]
        if "whites" in pick:
            ws = frozenset(pick["whites"])
            out.append(f"{g['k']}-ball set has appeared before ⚠️" if ws in history_sets
                       else f"{g['k']}-ball set **never drawn** in your file ✅")
        elif "digits" in pick:
            s = "".join(map(str, pick["digits"]))
            hits = int((df["digit_str"] == s).sum())
            box = int((df["digit_sorted"] == "".join(sorted(s))).sum())
            out.append(f"drawn straight **{hits}×**, box **{box}×** in your file "
                       "(with only 10^{} combos, repeats are routine)".format(g["d"]))
        else:
            out.append(f"popped **{pop_freq.get(pick['pop'], 0)}×** in your file")
        return out

    def render_pick(pick: dict, source: str, intention: str | None = None, attempts: int | None = None):
        st.markdown(f"### {fmt_pick(pick)}")
        bits = [f"Source: **{source}**"]
        if attempts:
            bits.append(f"attempts to find never-drawn set: {attempts}")
        bits += history_flags(pick)
        st.caption(" · ".join(bits))
        st.session_state.picks.append({
            "#": len(st.session_state.picks) + 1,
            "Generated At": pd.Timestamp.now().strftime("%m/%d/%Y %I:%M:%S %p"),
            "Game": game_name,
            "Numbers": pick_numbers_str(pick),
            "Source": source,
            "Intention": intention or "",
        })
        st.toast("Pick saved to 💾 My Picks", icon="💾")

    st.markdown("---")
    st.subheader("🧿 Intention Generator (Randonautica mode)")
    st.caption("Your intention is SHA-256 hashed and XOR-mixed with quantum bytes fetched the moment "
               "you commit — output depends on both. (No physics evidence intention steers quantum "
               "outcomes; the distribution stays perfectly uniform. Great ritual though.)")
    ic1, ic2 = st.columns([3, 1])
    intention = ic1.text_input("Your intention", placeholder="e.g., abundance for my family",
                               label_visibility="collapsed")
    if ic2.button("🧿 Commit intention", type="primary", use_container_width=True):
        if not intention.strip():
            st.warning("Set an intention first — even one word.")
        else:
            pick, src = generate(game_name, "intention", intention=intention)
            render_pick(pick, src, intention=intention.strip())
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("⚛️ Quantum pick")
        if st.button("Generate quantum numbers", type="primary"):
            pick, src = generate(game_name, "quantum")
            render_pick(pick, src)

        st.subheader("🛡️ Crypto-secure quick pick")
        if st.button("Generate secure pick"):
            pick, src = generate(game_name, "secure")
            render_pick(pick, src)

        if g["kind"] == "matrix":
            st.subheader("🆕 Guaranteed never-drawn set")
            if df is None:
                st.caption("Upload a history file to enable.")
            else:
                st.caption("Regenerates until the main-ball set has zero appearances in your file. "
                           "Fun filter, not an edge.")
                if st.button("Generate virgin combination"):
                    tries = 0
                    while True:
                        tries += 1
                        pick, src = generate(game_name, "secure")
                        if frozenset(pick["whites"]) not in history_sets:
                            break
                    render_pick(pick, src + " + history filter", attempts=tries)
        else:
            st.subheader("🆕 Never-drawn?")
            st.caption(f"Not offered for {game_name}: with so few possible outcomes, everything has "
                       "been drawn many times — the generators above report how often instead.")

    with c2:
        if g["kind"] == "matrix" and g["n"] > 40:
            st.subheader("💰 Anti-popularity pick (the honest edge)")
            st.caption("Main balls > 31 to dodge birthday pickers. Doesn't change win odds, but a "
                       "shared-jackpot game pays you more when fewer co-winners split it.")
            if st.button("Generate anti-popularity pick"):
                pick, src = generate(game_name, "anti")
                render_pick(pick, src)
        elif g["kind"] == "digit":
            st.subheader("💰 Anti-popularity?")
            st.caption("Pick 3/4 prizes are fixed per ticket — no sharing — so unpopular numbers "
                       "carry zero benefit here. (In pari-mutuel digit states they would; not SC.)")
        elif g["kind"] == "pop":
            st.subheader("💰 Anti-popularity?")
            st.caption("CASH POP prizes are assigned at purchase — number popularity is irrelevant.")

        freq_for_game = white_freq if g["kind"] == "matrix" else digit_freq if g["kind"] == "digit" else pop_freq
        st.subheader("🔥 Hot pick")
        if df is None:
            st.caption("Upload a history file to enable hot/cold picks.")
        else:
            st.caption("Sampled from the most-drawn numbers. Entertainment — streaks don't persist.")
            if st.button("Generate hot pick"):
                if g["kind"] == "pop":
                    pick = {"pop": freq_for_game.most_common(1)[0][0]}
                    render_pick(pick, "Most-drawn CASH POP number")
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="hot")
                    render_pick(pick, src)

            st.subheader("🧊 Cold pick")
            st.caption("Least-drawn numbers. 'Due' is the gambler's fallacy — equally (in)effective.")
            if st.button("Generate cold pick"):
                if g["kind"] == "pop":
                    ranked = [n for n, _ in freq_for_game.most_common()]
                    ranked += [n for n in range(1, g["n"] + 1) if n not in ranked]
                    pick = {"pop": ranked[-1]}
                    render_pick(pick, "Least-drawn CASH POP number")
                else:
                    pick, src = generate(game_name, "hotcold", freq=freq_for_game, mode="cold")
                    render_pick(pick, src)

# ============================================================================
# MY PICKS TAB
# ============================================================================
with tab_picks:
    st.subheader("💾 Every number you've generated this session — all games")
    if not st.session_state.get("picks"):
        st.info("No picks yet — every pick from any game is saved here automatically.")
    else:
        picks_df = pd.DataFrame(st.session_state.picks)
        st.dataframe(picks_df, hide_index=True, use_container_width=True)
        d1, d2, d3 = st.columns([1, 1, 2])
        d1.download_button("⬇️ Download picks CSV",
                           picks_df.to_csv(index=False).encode(),
                           file_name=f"my_sc_lottery_picks_{date.today():%Y%m%d}.csv",
                           mime="text/csv", type="primary")
        if d2.button("🗑️ Clear all picks"):
            st.session_state.picks = []
            st.rerun()
        d3.caption(f"{len(picks_df)} pick(s). Session-based — download before closing the tab.")

# ============================================================================
# FREQUENCY TAB
# ============================================================================
with tab_freq:
    if df is None:
        st.info(f"No history loaded for {game_name}. Upload a CSV in the sidebar "
                "(date column + winning-numbers column) to unlock frequency analysis.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Draws analyzed", f"{len(df):,}")
        c2.metric("Date range", f"{df['Draw Date'].min():%b %Y} – {df['Draw Date'].max():%b %Y}")

        if g["kind"] == "matrix":
            if g.get("era_start") is not None:
                use_era = st.checkbox(f"Current-rules era only (since {g['era_start']:%b %d, %Y})",
                                      value=False)
                dfe = df[df["Draw Date"] >= g["era_start"]] if use_era else df
            else:
                dfe = df
            wf_c = Counter(dfe[[f"W{i+1}" for i in range(g["k"])]].values.ravel())
            wf = pd.DataFrame({"Number": range(1, g["n"] + 1),
                               "Times Drawn": [wf_c.get(x, 0) for x in range(1, g["n"] + 1)]})
            st.subheader(f"Main balls (1–{g['n']})")
            st.caption(f"Uniform expectation: {len(dfe) * g['k'] / g['n']:.1f} per number — "
                       "deviations are normal sampling noise.")
            st.bar_chart(wf.set_index("Number"))
            h1, h2 = st.columns(2)
            h1.markdown("**🔥 Hottest 10**")
            h1.dataframe(wf.nlargest(10, "Times Drawn"), hide_index=True, use_container_width=True)
            h2.markdown("**🧊 Coldest 10**")
            h2.dataframe(wf.nsmallest(10, "Times Drawn"), hide_index=True, use_container_width=True)
            if g["bonus_n"]:
                bf_c = Counter(dfe["Bonus"])
                st.subheader(f"{g['bonus_name']} (1–{g['bonus_n']} under current rules)")
                bf = pd.DataFrame({"Number": range(1, g["bonus_n"] + 1),
                                   "Times Drawn": [bf_c.get(x, 0) for x in range(1, g["bonus_n"] + 1)]})
                st.bar_chart(bf.set_index("Number"))

        elif g["kind"] == "digit":
            st.subheader("Digit frequency — overall")
            odf = pd.DataFrame({"Digit": range(10),
                                "Times Drawn": [digit_freq.get(x, 0) for x in range(10)]})
            st.bar_chart(odf.set_index("Digit"))
            st.subheader("Digit frequency — by position")
            pos_cols = st.columns(g["d"])
            for i in range(g["d"]):
                pc = Counter(df[f"D{i+1}"])
                with pos_cols[i]:
                    st.markdown(f"**Position {i+1}**")
                    st.dataframe(pd.DataFrame({"Digit": range(10),
                                               "×": [pc.get(x, 0) for x in range(10)]}),
                                 hide_index=True, use_container_width=True, height=240)
            st.subheader("Most / least drawn straight combos")
            top = df["digit_str"].value_counts()
            t1, t2 = st.columns(2)
            t1.markdown("**Most repeated**")
            t1.dataframe(top.head(10).rename_axis("Combo").reset_index(name="Times"), hide_index=True)
            t2.metric("Distinct combos seen", f"{df['digit_str'].nunique():,} of {10**g['d']:,}")

        else:  # pop
            st.subheader("CASH POP number frequency (1–15)")
            pf = pd.DataFrame({"Number": range(1, 16),
                               "Times Drawn": [pop_freq.get(x, 0) for x in range(1, 16)]})
            st.bar_chart(pf.set_index("Number"))
            st.caption(f"Uniform expectation: {len(df)/15:.1f} per number.")

# ============================================================================
# CHECKER TAB
# ============================================================================
with tab_check:
    st.subheader(f"Check numbers against {game_name} history")
    if df is None:
        st.info("Upload a history CSV in the sidebar to enable checking.")
    else:
        if g["kind"] == "matrix":
            cols = st.columns(g["k"] + (1 if g["bonus_n"] else 0))
            whites_in = [cols[i].number_input(f"Ball {i+1}", 1, g["n"], value=min(7 * (i + 1), g["n"]),
                                              key=f"cw{i}") for i in range(g["k"])]
            bonus_in = (cols[-1].number_input(g["bonus_name"], 1, g["bonus_n"], value=7)
                        if g["bonus_n"] else None)
            if st.button("Check history", type="primary"):
                if len(set(whites_in)) != g["k"]:
                    st.error("Main balls must all be different.")
                else:
                    ws = frozenset(int(x) for x in whites_in)
                    five = df[df["white_set"] == ws]
                    if g["bonus_n"]:
                        exact = five[five["Bonus"] == bonus_in]
                        if len(exact):
                            st.error(f"😱 Exact combo hit the JACKPOT on {exact.iloc[0]['Draw Date']:%m/%d/%Y}.")
                        elif len(five):
                            st.warning(f"The {g['k']} main balls hit together on "
                                       f"{five.iloc[0]['Draw Date']:%m/%d/%Y} (different {g['bonus_name']}).")
                        else:
                            st.success("✅ Never drawn in your file.")
                    else:
                        if len(five):
                            st.error(f"😱 This set won the JACKPOT on {five.iloc[0]['Draw Date']:%m/%d/%Y}.")
                        else:
                            st.success("✅ Never drawn in your file.")
                    # would-have-won scan
                    rows = []
                    for _, r in df.iterrows():
                        wm = len(ws & r["white_set"])
                        bm = (bonus_in == r["Bonus"]) if g["bonus_n"] else None
                        label = next((t[3] for t in g["tiers"]
                                      if t[0] == wm and (t[1] is None or t[1] == bm)), None)
                        if label:
                            rows.append({"Draw Date": r["Draw Date"].date(),
                                         "Matched": f"{wm}" + (f" + {g['bonus_name']}" if bm else ""),
                                         "Tier": label})
                    if rows:
                        st.markdown(f"**Draws where these numbers would have won: {len(rows)}**")
                        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                    else:
                        st.info("These numbers would never have won any tier in the file.")

        elif g["kind"] == "digit":
            cols = st.columns(g["d"])
            digs = [cols[i].number_input(f"Digit {i+1}", 0, 9, value=i + 1, key=f"cd{i}")
                    for i in range(g["d"])]
            if st.button("Check history", type="primary"):
                s = "".join(map(str, digs))
                straight = df[df["digit_str"] == s]
                box = df[df["digit_sorted"] == "".join(sorted(s))]
                m1, m2, m3 = st.columns(3)
                m1.metric("Straight hits", len(straight))
                m2.metric("Box hits", len(box))
                m3.metric("Box type", f"{digit_box_ways([int(c) for c in s])}-way")
                if len(box):
                    st.dataframe(box[["Draw Date", "digit_str"]].head(25)
                                 .rename(columns={"digit_str": "Drawn"}),
                                 hide_index=True, use_container_width=True)

        else:
            pop_in = st.number_input("Your CASH POP number", 1, 15, value=7)
            if st.button("Check history", type="primary"):
                hits = df[df["Pop"] == pop_in]
                st.metric(f"Number {pop_in} popped", f"{len(hits)}× in {len(df)} drawings",
                          delta=f"expected {len(df)/15:.1f}")

# ============================================================================
# ODDS & EV TAB
# ============================================================================
with tab_odds:
    st.subheader(f"{game_name} — exact odds & expected value")

    if g["kind"] == "matrix":
        n, k = g["n"], g["k"]
        if g["bonus_n"]:
            st.latex(rf"P(k\text{{ balls}}) = \frac{{\binom{{{k}}}{{k}}\binom{{{n-k}}}{{{k}-k}}}}{{\binom{{{n}}}{{{k}}}}} \times P(\text{{bonus}})")
        jc1, jc2 = st.columns(2)
        jackpot = jc1.number_input("Jackpot CASH value ($)", min_value=10_000,
                                   value=g["default_jackpot"], step=10_000, format="%d")
        co = jc2.number_input("Expected winners sharing jackpot", 1.0, value=1.0, step=0.25) \
            if g["sharing"] else 1.0

        rows, ev = [], 0.0
        editable = {}
        st.markdown("**Prize table** (non-jackpot amounts editable — verify vs official rules PDF):")
        for idx, (km, bm, prize, label) in enumerate(g["tiers"]):
            p = matrix_tier_probability(g, km, bm)
            if prize is None:
                val = jackpot / max(co, 1.0)
            else:
                val = st.session_state.get(f"prize_{game_name}_{idx}", prize)
            mult = mm_expected_multiplier if game_name == "Mega Millions" and prize is not None else 1.0
            contrib = p * val * mult
            ev += contrib
            rows.append({"Tier": label, "Odds": f"1 in {round(1/p):,}",
                         "Prize ($)": "JACKPOT" if prize is None else f"{val:,.0f}",
                         "EV contribution ($)": f"{contrib:.4f}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        with st.expander("✏️ Edit non-jackpot prize amounts"):
            for idx, (km, bm, prize, label) in enumerate(g["tiers"]):
                if prize is not None:
                    st.number_input(label, min_value=0, value=prize,
                                    key=f"prize_{game_name}_{idx}")

        any_p = sum(matrix_tier_probability(g, km, bm) for km, bm, _, _ in g["tiers"])
        e1, e2, e3 = st.columns(3)
        e1.metric("Any prize", f"1 in {1/any_p:.1f}")
        e2.metric(f"EV per ${g['price']:.0f} ticket", f"${ev:.2f}")
        e3.metric("Expected loss per ticket", f"${g['price'] - ev:.2f}",
                  delta=f"{(ev/g['price'] - 1)*100:.0f}% return", delta_color="inverse")
        if game_name == "Mega Millions":
            st.caption(f"Includes built-in multiplier (expected {mm_expected_multiplier:.2f}×) on non-jackpot prizes.")

    elif g["kind"] == "digit":
        st.markdown("Enter the digits you'd play — box odds depend on repeats:")
        cols = st.columns(g["d"])
        digs = [cols[i].number_input(f"Digit {i+1}", 0, 9, value=i + 1, key=f"od{i}")
                for i in range(g["d"])]
        ways = digit_box_ways([int(x) for x in digs])
        total = 10 ** g["d"]
        st.markdown("**Play types for your digits** (payouts editable — verify vs official rules PDF):")
        rows = []
        straight_pay = st.session_state.get(f"pay_{game_name}_straight", g["plays"]["Straight"])
        rows.append({"Play": "Straight (exact order)", "Odds": f"1 in {total:,}",
                     "Payout per $1": f"${straight_pay:,}",
                     "EV per $1": f"${straight_pay/total:.3f}"})
        if ways > 1:
            box_label = f"Box ({ways}-way)"
            box_pay_default = g["plays"].get(box_label, round(straight_pay / ways / 5) * 5)
            box_pay = st.session_state.get(f"pay_{game_name}_box", box_pay_default)
            rows.append({"Play": f"{box_label} (any order)", "Odds": f"1 in {total//ways:,}",
                         "Payout per $1": f"${box_pay:,}",
                         "EV per $1": f"${box_pay*ways/total:.3f}"})
        else:
            rows.append({"Play": "Box", "Odds": "n/a — all digits identical (straight only)",
                         "Payout per $1": "—", "EV per $1": "—"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        with st.expander("✏️ Edit payouts"):
            st.number_input("Straight payout", 0, value=g["plays"]["Straight"],
                            key=f"pay_{game_name}_straight")
            if ways > 1:
                st.number_input("Box payout", 0,
                                value=g["plays"].get(f"Box ({ways}-way)",
                                                     round(g["plays"]["Straight"]/ways/5)*5),
                                key=f"pay_{game_name}_box")
        st.caption("FIREBALL (doubles your wager) adds a drawn digit that can substitute for any one "
                   f"drawn digit, creating extra winning combos at reduced payouts — official odds run "
                   f"{'1 in 37 to 1 in 10,000' if g['d']==3 else '1 in 149 to 1 in 100,000'}. "
                   "EV math: FIREBALL roughly preserves the game's payout percentage — it buys more "
                   "chances, not better ones.")

    else:  # CASH POP
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
    ' · Columbia, SC · For entertainment and education — play responsibly · '
    '<a href="https://www.sceducationlottery.com/PlayResponsibly" target="_blank" rel="noopener">Play Responsibly SC</a></div>',
    unsafe_allow_html=True,
)
