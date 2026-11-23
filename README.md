# Oil vs. Electrons

**A self-updating quant dashboard on the transport-energy transition.**
It answers one question with market data: *what does it cost to move a car one
mile on gasoline vs. electricity, today and over the next 12 months, and how do
oil and EV equities price that shift?*

Live site: `https://<your-github-username>.github.io/oil-vs-electrons/`

## What it does

| Section | Quant content |
|---|---|
| Oil market | WTI futures curve (≈20 contracts), contango/backwardation, annualised roll yield, implied net convenience yield from cost-of-carry, 3-2-1 crack spread, retail-vs-wholesale gasoline spread |
| Fuel economics | Cost per mile: gasoline (EIA retail) vs. EV at home (BLS electricity price) vs. public DC fast charging; breakeven gasoline and WTI prices via a pump-price pass-through regression |
| 12-month outlook | WTI path from the futures curve with lognormal 50%/90% bands from the USO implied-vol term structure; risk-neutral probabilities (N(d₂)) of ±20% moves and of fast charging beating gasoline |
| Equities | Two-factor OLS (S&P 500 + WTI) for oil, EV-maker and EV-charging names and equal-weight baskets; rolling 6-month oil beta; the "long EV / short oil" spread |
| Options & risk | Implied vols solved from bid/ask mids with Black-Scholes + Brent's method, ATM term structure, 30-day smile and skew, implied-vs-realised (variance risk premium), Greeks of a 30-day ATM option, realised vol, historical & EWMA VaR / Expected Shortfall |
| Tracking log | Curve snapshots and key metrics appended every trading day, so the history charts grow over time |

The "Today's read" commentary is generated from the numbers on every run, so the
text never goes stale.

## How it stays alive

`.github/workflows/update.yml` runs every weekday at 22:15 UTC (after the US close):

1. `python scripts/build.py` pulls Yahoo Finance (futures, equities, option chains) and FRED (Treasuries, EIA gasoline, BLS electricity).
2. It runs the analytics and writes `site/data/latest.json`.
3. It commits the growing history (`data/curve_history.json`, `data/metrics_history.csv`).
4. It deploys `site/` to GitHub Pages.

A failing data source is logged and skipped; the rest of the page still updates.

## Run locally

```bash
pip install -r requirements.txt
python scripts/build.py          # live data
python scripts/build.py --demo   # synthetic data, offline
python -m http.server -d site 8000   # open http://localhost:8000
```

## Layout

```
scripts/config.py     tickers, baskets, cost-per-mile assumptions
scripts/sources.py    Yahoo/FRED access + offline demo generator
scripts/analytics.py  Black-Scholes, implied vol, Greeks, factor model, VaR
scripts/build.py      pipeline, history log, auto-commentary → JSON
site/                 static page (HTML/CSS + Plotly.js)
data/                 accumulated history (committed by the workflow)
```

## Caveats

Risk-neutral probabilities include risk premia; they are not physical forecasts.
American options and ETF dividends are approximated as European. The front-month
WTI series has roll gaps. Fast-charging price and vehicle efficiencies are stated
assumptions (`scripts/config.py`). For education only; not investment advice.

---
Xiaoyu (Laurel) Chen · Duke University · EGRMGMT 534 Final Project
