# SC Lottery Analysis Lab

Streamlit app covering all six South Carolina Education Lottery terminal games: Mega Millions, Powerball, Palmetto Cash 5, Pick 4 + FIREBALL, Pick 3 + FIREBALL, and CASH POP.

Odds and prize tables follow current official rules (Mega Millions $5 matrix since April 2025, Palmetto Cash 5 $2 built-in multiplier since October 2025). Frequency tools describe the past only — they do not change the odds.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run sc_lottery_lab.py
```

`mega_millions_lab.py` is a backward-compatible entry point that loads the same app.

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io), create an app from the repo.
3. Set **Main file path** to `sc_lottery_lab.py`.
4. Leave Python to the `runtime.txt` version (3.12).

Optional: add a secret `ANU_QRNG_KEY` if you want the current ANU Quantum Numbers API. Without it the app tries the public legacy endpoint and falls back to a crypto-secure generator.

## History CSV format

| Column | Example |
| --- | --- |
| Draw Date | `07/14/2026` |
| Winning Numbers | `02 04 10 48 56` |
| Mega Ball / Powerball | `22` (matrix games with a bonus ball) |

Dashes and commas are accepted. Mega Millions history ships in `export.csv` and loads automatically.

## Responsible play

For entertainment and education. Play only with money you can afford to lose. [Play Responsibly SC](https://www.sceducationlottery.com/PlayResponsibly)
