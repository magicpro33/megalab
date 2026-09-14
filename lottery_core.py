"""Pure lottery math, history parsing, and pick generation — no Streamlit UI."""

from __future__ import annotations

import hashlib
import io
import math
import re
import secrets
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

NUM_RE = re.compile(r"\d+")

# Official built-in multiplier odds (probability = 1 / published "1 in X").
MM_MULTIPLIER_ODDS = {2: 2.1333, 3: 3.2, 4: 8.0, 5: 16.0, 10: 32.0}
PC5_MULTIPLIER_ODDS = {2: 3.17, 3: 3.80, 5: 3.80, 10: 6.33}

GAMES = {
    "Mega Millions": dict(
        kind="matrix",
        k=5,
        n=70,
        bonus_n=24,
        bonus_name="Mega Ball",
        price=5.0,
        sharing=True,
        default_jackpot=200_000_000,
        tiers=[
            (5, True, None, "JACKPOT"),
            (5, False, 1_000_000, "Match 5"),
            (4, True, 10_000, "Match 4 + MB"),
            (4, False, 500, "Match 4"),
            (3, True, 200, "Match 3 + MB"),
            (3, False, 10, "Match 3"),
            (2, True, 10, "Match 2 + MB"),
            (1, True, 7, "Match 1 + MB"),
            (0, True, 5, "Mega Ball only"),
        ],
        multipliers=MM_MULTIPLIER_ODDS,
        note=(
            "Current rules (since Apr 8, 2025): $5 ticket includes a 2×–10× multiplier "
            "on every non-jackpot prize. Base prizes below are official pre-multiplier amounts."
        ),
        era_start=pd.Timestamp("2025-04-08"),
        white70_start=pd.Timestamp("2017-10-31"),
        preload="export.csv",
        official_any_odds=23.0737,
    ),
    "Powerball": dict(
        kind="matrix",
        k=5,
        n=69,
        bonus_n=26,
        bonus_name="Powerball",
        price=2.0,
        sharing=True,
        default_jackpot=250_000_000,
        tiers=[
            (5, True, None, "JACKPOT"),
            (5, False, 1_000_000, "Match 5"),
            (4, True, 50_000, "Match 4 + PB"),
            (4, False, 100, "Match 4"),
            (3, True, 100, "Match 3 + PB"),
            (3, False, 7, "Match 3"),
            (2, True, 7, "Match 2 + PB"),
            (1, True, 4, "Match 1 + PB"),
            (0, True, 4, "Powerball only"),
        ],
        multipliers=None,
        note=(
            "Power Play (extra $1) multiplies most non-jackpot prizes; Match 5 with Power Play "
            "is $2 million. EV below is the $2 base ticket without Power Play."
        ),
        era_start=pd.Timestamp("2015-10-07"),
        official_any_odds=24.87,
    ),
    "Palmetto Cash 5": dict(
        kind="matrix",
        k=5,
        n=42,
        bonus_n=None,
        bonus_name=None,
        price=2.0,
        sharing=True,
        default_jackpot=100_000,
        tiers=[
            (5, None, None, "JACKPOT"),
            (4, None, 300, "Match 4"),
            (3, None, 5, "Match 3"),
            (2, None, 1, "Match 2"),
        ],
        multipliers=PC5_MULTIPLIER_ODDS,
        note=(
            "SC-only, drawn nightly. $2 play includes a built-in 2×/3×/5×/10× multiplier on "
            "non-jackpot prizes. Jackpot starts at $100,000 and is pari-mutuel."
        ),
        era_start=pd.Timestamp("2025-10-15"),
        official_any_odds=10.0,
    ),
    "Pick 4 + FIREBALL": dict(
        kind="digit",
        d=4,
        price=1.0,
        sharing=False,
        note=(
            "Digits 0–9, repeats allowed. FIREBALL (doubles the wager) adds a drawn digit that "
            "can replace any one of the four. Official $1 odds: 1 in 417 to 1 in 10,000 by play type."
        ),
        plays={
            "Straight": 5000,
            "Box (24-way)": 200,
            "Box (12-way)": 400,
            "Box (6-way)": 800,
            "Box (4-way)": 1200,
        },
    ),
    "Pick 3 + FIREBALL": dict(
        kind="digit",
        d=3,
        price=1.0,
        sharing=False,
        note=(
            "Digits 0–9, repeats allowed. FIREBALL (doubles the wager) adds a drawn digit that "
            "can replace any one of the three. Official $1 odds: 1 in 100 to 1 in 1,000 by play type."
        ),
        plays={"Straight": 500, "Box (6-way)": 80, "Box (3-way)": 160},
    ),
    "CASH POP": dict(
        kind="pop",
        n=15,
        price=1.0,
        sharing=False,
        note=(
            "Pick one number 1–15; one number is drawn (Midday & Evening). Odds 1 in 15. "
            "Prize amount is assigned at purchase ($1 play pays $5–$100; higher wagers scale "
            "up to $2,500)."
        ),
    ),
}


def odds_to_probs(odds: dict[int, float]) -> dict[int, float]:
    raw = {m: 1.0 / x for m, x in odds.items()}
    total = sum(raw.values())
    return {m: p / total for m, p in raw.items()}


def expected_multiplier(odds: dict[int, float] | None) -> float:
    if not odds:
        return 1.0
    return sum(m * p for m, p in odds_to_probs(odds).items())


def matrix_tier_probability(g: dict, k_match: int, bonus: bool | None) -> float:
    ways = math.comb(g["k"], k_match) * math.comb(g["n"] - g["k"], g["k"] - k_match)
    p = ways / math.comb(g["n"], g["k"])
    if g.get("bonus_n"):
        p *= (1 / g["bonus_n"]) if bonus else ((g["bonus_n"] - 1) / g["bonus_n"])
    return p


def any_prize_probability(g: dict) -> float:
    return sum(matrix_tier_probability(g, km, bm) for km, bm, _, _ in g["tiers"])


def digit_box_ways(digits: list[int]) -> int:
    """Number of distinct arrangements of the chosen digits (box 'ways')."""
    counts = Counter(digits)
    ways = math.factorial(len(digits))
    for v in counts.values():
        ways //= math.factorial(v)
    return ways


def parse_int_tokens(value) -> list[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [int(x) for x in NUM_RE.findall(str(value))]


def parse_digit_row(value, d: int) -> list[int] | None:
    tokens = parse_int_tokens(value)
    if len(tokens) >= d and all(0 <= t <= 9 for t in tokens[:d]):
        return tokens[:d]
    if len(tokens) == 1:
        padded = f"{tokens[0]:0{d}d}"
        if len(padded) == d and padded.isdigit():
            return [int(c) for c in padded]
    digits = [int(c) for c in re.findall(r"\d", str(value))]
    if len(digits) >= d:
        return digits[:d]
    return None


def _find_col(columns: list[str], *needles: str) -> str | None:
    lowered = [(c, c.lower().replace(" ", "")) for c in columns]
    for needle in needles:
        key = needle.lower().replace(" ", "")
        for original, compact in lowered:
            if key and key in compact:
                return original
    return None


def _number_col(columns: list[str], bonus_name: str | None) -> str | None:
    skip = {"multiplier", "megaplier", "powerplay"}
    if bonus_name:
        skip.add(bonus_name.lower().replace(" ", ""))
    winning = _find_col(columns, "winning")
    if winning:
        return winning
    for c in columns:
        compact = c.lower().replace(" ", "")
        if "number" in compact and compact not in skip and "date" not in compact:
            return c
    return None


def parse_history(game: dict, raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise ValueError("The file has no rows.")

    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    date_col = _find_col(list(df.columns), "date") or df.columns[0]
    df["Draw Date"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["Draw Date"])
    if df.empty:
        raise ValueError("No valid dates found. Need a date column (e.g. Draw Date).")

    num_col = _number_col(list(df.columns), game.get("bonus_name"))
    if num_col is None:
        raise ValueError(
            "Need a winning-numbers column (name containing 'winning' or 'number')."
        )

    if game["kind"] == "matrix":
        whites, bonuses, keep = [], [], []
        bonus_col = None
        if game.get("bonus_name"):
            bonus_col = _find_col(list(df.columns), game["bonus_name"], "bonusball", "bonus")
            if bonus_col == num_col:
                bonus_col = None
        for _, row in df.iterrows():
            tokens = parse_int_tokens(row[num_col])
            if len(tokens) < game["k"]:
                continue
            w = tokens[: game["k"]]
            if len(set(w)) != game["k"] or any(x < 1 for x in w):
                continue
            b = None
            if game.get("bonus_n"):
                if bonus_col is not None:
                    btoks = parse_int_tokens(row[bonus_col])
                    if btoks:
                        b = btoks[0]
                elif len(tokens) > game["k"]:
                    b = tokens[game["k"]]
                if b is None or b < 1:
                    continue
            whites.append(w)
            bonuses.append(b)
            keep.append(row.name)
        if not keep:
            raise ValueError(
                f"Could not parse {game['k']} main numbers "
                f"{'plus a bonus ball ' if game.get('bonus_n') else ''}"
                "from this file."
            )
        df = df.loc[keep].copy()
        for i in range(game["k"]):
            df[f"W{i + 1}"] = [w[i] for w in whites]
        df["white_set"] = [frozenset(w) for w in whites]
        if game.get("bonus_n"):
            df["Bonus"] = bonuses
    elif game["kind"] == "digit":
        digits, keep = [], []
        for _, row in df.iterrows():
            parsed = parse_digit_row(row[num_col], game["d"])
            if parsed is None:
                continue
            digits.append(parsed)
            keep.append(row.name)
        if not keep:
            raise ValueError(f"Could not parse {game['d']} digits from this file.")
        df = df.loc[keep].copy()
        for i in range(game["d"]):
            df[f"D{i + 1}"] = [d[i] for d in digits]
        df["digit_str"] = ["".join(str(x) for x in d) for d in digits]
        df["digit_sorted"] = ["".join(sorted(s)) for s in df["digit_str"]]
    else:
        pops, keep = [], []
        for _, row in df.iterrows():
            tokens = parse_int_tokens(row[num_col])
            if not tokens:
                continue
            n = tokens[0]
            if 1 <= n <= game["n"]:
                pops.append(n)
                keep.append(row.name)
        if not keep:
            raise ValueError(f"Could not parse CASH POP numbers (1–{game['n']}) from this file.")
        df = df.loc[keep].copy()
        df["Pop"] = pops

    return df.sort_values("Draw Date", ascending=False).reset_index(drop=True)


def load_game_history(
    game_name: str,
    file_bytes: bytes | None,
    data_dir: str | Path | None = None,
) -> tuple[pd.DataFrame | None, str | None]:
    game = GAMES[game_name]
    df_raw = None
    if file_bytes:
        try:
            df_raw = pd.read_csv(io.BytesIO(file_bytes))
        except Exception as exc:
            return None, f"Could not read CSV: {exc}"
    elif game.get("preload"):
        path = Path(data_dir or ".") / game["preload"]
        if not path.is_file():
            return None, None
        try:
            df_raw = pd.read_csv(path)
        except Exception as exc:
            return None, f"Could not read {path.name}: {exc}"
    else:
        return None, None

    try:
        return parse_history(game, df_raw), None
    except Exception as exc:
        return None, str(exc)


def fetch_quantum_bytes(n: int = 64, api_key: str | None = None) -> tuple[bytes, bool]:
    attempts: list[tuple[str, dict, dict]] = []
    if api_key:
        attempts.append(
            (
                "https://api.quantumnumbers.anu.edu.au",
                {"length": n, "type": "uint8"},
                {"x-api-key": api_key},
            )
        )
    attempts.append(
        (
            "https://qrng.anu.edu.au/API/jsonI.php",
            {"length": n, "type": "uint8"},
            {},
        )
    )
    for url, params, headers in attempts:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=6)
            r.raise_for_status()
            if "json" not in r.headers.get("content-type", "").lower():
                continue
            data = r.json().get("data")
            if not data:
                continue
            return bytes(int(x) & 0xFF for x in data), True
        except Exception:
            continue
    return secrets.token_bytes(n), False


def pool_sampler(pool_bytes: bytes):
    pool = list(
        hashlib.sha512(pool_bytes).digest()
        + hashlib.sha512(pool_bytes[::-1]).digest()
        + pool_bytes
    )

    def draw(n: int) -> int:
        if n <= 0:
            raise ValueError("draw size must be positive")
        limit = 256 - (256 % n)
        while pool:
            b = pool.pop()
            if b < limit:
                return b % n
        return secrets.randbelow(n)

    return draw


def generate(
    game_name: str,
    method: str,
    intention: str = "",
    freq: Counter | None = None,
    mode: str = "hot",
    api_key: str | None = None,
) -> tuple[dict, str]:
    g = GAMES[game_name]
    rng = secrets.SystemRandom()

    if method in ("quantum", "intention"):
        qb, live = fetch_quantum_bytes(api_key=api_key)
        if method == "intention":
            seed = hashlib.sha256(intention.strip().lower().encode()).digest()
            qb = bytes(q ^ seed[i % 32] for i, q in enumerate(qb))
            src = (
                "ANU Quantum RNG ⊕ intention hash"
                if live
                else "CSPRNG ⊕ intention hash (quantum offline)"
            )
        else:
            src = "ANU Quantum RNG (live)" if live else "Quantum offline — CSPRNG fallback"
        draw = pool_sampler(qb)
    else:
        draw = lambda n: rng.randrange(n)
        src = {
            "secure": "Crypto-secure CSPRNG",
            "anti": "CSPRNG, birthday-range excluded",
            "hotcold": f"Frequency-weighted ({mode})",
        }.get(method, "CSPRNG")

    if g["kind"] == "matrix":
        lo, pool_hi = (32 if method == "anti" else 1), g["n"]
        if method == "anti" and pool_hi - lo + 1 < g["k"]:
            lo = 1
        if method == "hotcold" and freq:
            ranked = [x for x, _ in freq.most_common() if 1 <= x <= g["n"]]
            ranked += [x for x in range(1, g["n"] + 1) if x not in ranked]
            width = min(20, g["n"])
            cand = ranked[:width] if mode == "hot" else ranked[-width:]
            if len(cand) < g["k"]:
                cand = list(range(1, g["n"] + 1))
            whites = sorted(rng.sample(cand, g["k"]))
        else:
            whites_set: set[int] = set()
            span = pool_hi - lo + 1
            guard = 0
            while len(whites_set) < g["k"] and guard < 10_000:
                whites_set.add(lo + draw(span))
                guard += 1
            if len(whites_set) < g["k"]:
                pool = [x for x in range(lo, pool_hi + 1) if x not in whites_set]
                whites_set.update(rng.sample(pool, g["k"] - len(whites_set)))
            whites = sorted(whites_set)
        pick: dict = {"whites": whites}
        if g.get("bonus_n"):
            pick["bonus"] = 1 + draw(g["bonus_n"])
        return pick, src

    if g["kind"] == "digit":
        if method == "hotcold" and freq:
            ranked = [x for x, _ in freq.most_common() if 0 <= x <= 9]
            ranked += [x for x in range(10) if x not in ranked]
            cand = ranked[:5] if mode == "hot" else ranked[-5:]
            digits = [rng.choice(cand) for _ in range(g["d"])]
        else:
            digits = [draw(10) for _ in range(g["d"])]
        return {"digits": digits, "fireball": draw(10)}, src

    return {"pop": 1 + draw(g["n"])}, src


def never_drawn_pick(
    game_name: str,
    history_sets: set,
    max_tries: int = 8_000,
    api_key: str | None = None,
) -> tuple[dict, str, int]:
    for tries in range(1, max_tries + 1):
        pick, src = generate(game_name, "secure", api_key=api_key)
        if frozenset(pick["whites"]) not in history_sets:
            return pick, src + " + history filter", tries
    pick, src = generate(game_name, "secure", api_key=api_key)
    return pick, src + " + history filter (gave up — set may exist)", max_tries


def format_pick_markdown(pick: dict, bonus_name: str | None = None) -> str:
    if "whites" in pick:
        s = " ".join(f"`{w:02d}`" for w in pick["whites"])
        if "bonus" in pick:
            s += f"  —  🟡 {bonus_name or 'Bonus'} `{pick['bonus']:02d}`"
        return s
    if "digits" in pick:
        return " ".join(f"`{d}`" for d in pick["digits"]) + f"  —  🔥 FIREBALL `{pick['fireball']}`"
    return f"💥 `{pick['pop']}`"


def format_pick_plain(pick: dict) -> str:
    if "whites" in pick:
        s = " ".join(f"{w:02d}" for w in pick["whites"])
        return s + (f" + {pick['bonus']:02d}" if "bonus" in pick else "")
    if "digits" in pick:
        return "".join(map(str, pick["digits"])) + f" (FB {pick['fireball']})"
    return str(pick["pop"])
