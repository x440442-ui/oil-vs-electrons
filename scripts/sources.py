"""Data access layer.

`LiveSource` pulls from Yahoo Finance (yfinance) and FRED's public CSV
endpoint. `DemoSource` produces synthetic but realistic data with the same
shapes, so the whole pipeline and the page can be tested offline
(`python scripts/build.py --demo`).
"""
from __future__ import annotations

import io
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

MONTH_CODES = "FGHJKMNQUVXZ"
OPTION_TARGET_DAYS = [14, 30, 45, 60, 90, 120, 180, 270, 365]


def approx_cl_expiry(delivery_year: int, delivery_month: int) -> date:
    """WTI futures stop trading ~3 business days before the 25th of the month
    *before* delivery. The 20th of that month is a close-enough approximation
    for time-to-expiry maths."""
    y, m = (delivery_year, delivery_month - 1) if delivery_month > 1 else (delivery_year - 1, 12)
    return date(y, m, 20)


def candidate_cl_contracts(today: date, n: int):
    out = []
    y, m = today.year, today.month
    for _ in range(n + 3):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        exp = approx_cl_expiry(y, m)
        if exp <= today:
            continue
        out.append({
            "ticker": f"CL{MONTH_CODES[m - 1]}{str(y)[-2:]}.NYM",
            "label": date(y, m, 1).strftime("%b %y"),
            "expiry": exp,
        })
        if len(out) >= n:
            break
    return out


def pick_expiries(expiries: list[str], today: date) -> list[str]:
    dated = []
    for e in expiries:
        d = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
        if 5 <= d <= 400:
            dated.append((d, e))
    chosen = []
    for target in OPTION_TARGET_DAYS:
        if not dated:
            break
        d, e = min(dated, key=lambda x: abs(x[0] - target))
        if e not in chosen and abs(d - target) <= max(10, 0.35 * target):
            chosen.append(e)
    return sorted(chosen)


# =================================================================== live
class LiveSource:
    demo = False

    def __init__(self):
        import yfinance as yf  # imported lazily so --demo needs no network libs
        self.yf = yf

    def _batch(self, tickers, period):
        df = None
        for attempt in range(3):  # Yahoo occasionally rate-limits CI runners
            try:
                df = self.yf.download(tickers, period=period, auto_adjust=True,
                                      progress=False, threads=False)
                if df is not None and not df.empty:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5 * (attempt + 1))
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"].copy()
        else:
            close = df[["Close"]].copy()
            close.columns = tickers[:1]
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        return close

    def _single(self, t, period):
        for attempt in range(3):
            try:
                h = self.yf.Ticker(t).history(period=period, auto_adjust=True)
                if h is not None and not h.empty:
                    s = h["Close"].copy()
                    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                    return s
            except Exception:  # noqa: BLE001
                pass
            time.sleep(4 * (attempt + 1))
        return None

    def prices(self, tickers: list[str], period: str) -> pd.DataFrame:
        close = self._batch(tickers, period)
        # anything the batch call dropped gets a one-by-one retry
        for t in tickers:
            if t not in close.columns or close[t].dropna().empty:
                s = self._single(t, period)
                if s is not None:
                    close = close.join(s.rename(t), how="outer") if not close.empty else s.rename(t).to_frame()
                    if t in close.columns and isinstance(close[t], pd.DataFrame):
                        close = close.loc[:, ~close.columns.duplicated(keep="last")]
        close = close[~close.index.duplicated(keep="last")]
        return close.sort_index()

    def futures_curve(self, today: date, n: int) -> list[dict]:
        cands = candidate_cl_contracts(today, n)
        df = self.prices([c["ticker"] for c in cands], "10d")
        out = []
        for c in cands:
            if c["ticker"] not in df.columns:
                continue
            s = df[c["ticker"]].dropna()
            if s.empty or (pd.Timestamp(today) - s.index[-1]).days > 7:
                continue
            out.append({**c, "price": float(s.iloc[-1])})
        return out

    def option_chains(self, ticker: str, today: date):
        t = self.yf.Ticker(ticker)
        spot = float(t.history(period="5d")["Close"].dropna().iloc[-1])
        chains = []
        for e in pick_expiries(list(t.options), today):
            for attempt in range(3):
                try:
                    oc = t.option_chain(e)
                    chains.append((e, oc.calls.copy(), oc.puts.copy()))
                    break
                except Exception:  # transient Yahoo errors
                    time.sleep(1.5)
        return spot, chains

    # ---------------------------------------------------------------- FRED
    # fred.stlouisfed.org often times out from GitHub's cloud runners, so each
    # series has a fallback that goes to the original publisher instead.
    YAHOO_RATE_FALLBACK = {"DGS3MO": "^IRX", "DGS10": "^TNX", "DGS2": "2YY=F"}

    def fred(self, series_id: str) -> pd.Series:
        errs = []
        for fn in (self._fred_api, self._fred_csv, self._fallback):
            try:
                s = fn(series_id)
                if s is not None and len(s) > 5:
                    return s
            except Exception as e:  # noqa: BLE001
                errs.append(f"{fn.__name__}: {type(e).__name__}")
        raise RuntimeError("all sources failed (" + "; ".join(errs) + ")")

    def _fred_api(self, sid):
        import os
        import requests
        key = os.environ.get("FRED_API_KEY")
        if not key:
            return None
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": key, "file_type": "json",
                                 "observation_start": "2020-01-01"}, timeout=30)
        r.raise_for_status()
        obs = r.json()["observations"]
        s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in obs})
        return s.dropna()

    def _fred_csv(self, sid):
        import requests
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2020-01-01"
        r = requests.get(url, timeout=(10, 25), headers={"User-Agent": "Mozilla/5.0 oil-vs-electrons"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().set_index("date")["value"]

    def _fallback(self, sid):
        import requests
        if sid in self.YAHOO_RATE_FALLBACK:
            s = self._single(self.YAHOO_RATE_FALLBACK[sid], "5y")
            return s.dropna() if s is not None else None  # Yahoo quotes these in percent
        if sid == "GASREGW":  # EIA weekly US regular retail gasoline, public XLS
            url = "https://www.eia.gov/dnav/pet/hist_xls/EMM_EPMR_PTE_NUS_DPGw.xls"
            r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            df = pd.read_excel(io.BytesIO(r.content), sheet_name="Data 1", skiprows=2)
            s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").values,
                          index=pd.to_datetime(df.iloc[:, 0], errors="coerce"))
            s = s[s.index.notna()].dropna()
            return s[s.index >= "2020-01-01"]
        if sid == "APU000072610":  # BLS average price, public API v1 (no key)
            # BLS rejects requests without a browser-like User-Agent (returns HTML)
            r = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                              json={"seriesid": [sid]}, timeout=60,
                              headers={"User-Agent": "Mozilla/5.0 (Macintosh) oil-vs-electrons",
                                       "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()["Results"]["series"][0]["data"]
            pts = {pd.Timestamp(int(d["year"]), int(d["period"][1:]), 1): float(d["value"])
                   for d in data if d["period"].startswith("M") and d["period"] != "M13"
                   and d.get("value", "-").replace(".", "", 1).isdigit()}
            return pd.Series(pts).sort_index()
        return None


# =================================================================== demo
class DemoSource:
    """Synthetic data with realistic levels, vols and correlations."""
    demo = True

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self._cache = None

    def _universe(self):
        if self._cache is not None:
            return self._cache
        n = 252 * 3
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
        rng = self.rng
        mkt = rng.normal(0.0004, 0.011, n)
        oil = rng.normal(-0.0001, 0.021, n)
        spec = {  # beta_mkt, beta_oil, idio vol, start price
            "SPY": (1.0, 0.0, 0.0, 520), "CL=F": (0.25, 1.0, 0.0, 78),
            "BZ=F": (0.25, 0.97, 0.004, 82), "XLE": (0.8, 0.45, 0.008, 88),
            "XOM": (0.6, 0.45, 0.010, 112), "CVX": (0.7, 0.42, 0.010, 155),
            "VLO": (1.0, 0.35, 0.016, 140), "USO": (0.25, 1.0, 0.003, 74),
            "TSLA": (2.0, 0.05, 0.030, 240), "RIVN": (1.9, 0.08, 0.035, 15),
            "NIO": (1.6, 0.05, 0.035, 6), "XPEV": (1.7, 0.06, 0.035, 12),
            "LI": (1.5, 0.04, 0.030, 25), "CHPT": (1.9, 0.10, 0.045, 12),
            "EVGO": (2.0, 0.12, 0.045, 5), "BLNK": (2.0, 0.10, 0.045, 2.5),
        }
        data = {}
        for t, (bm, bo, iv, p0) in spec.items():
            r = bm * mkt + bo * oil + rng.normal(0, iv, n) if t not in ("SPY", "CL=F") else (mkt if t == "SPY" else 0.25 * mkt + oil)
            data[t] = p0 * np.exp(np.cumsum(r))
        df = pd.DataFrame(data, index=idx)
        # products: tie to crude so crack spread is realistic
        crack = 24 + 6 * np.sin(np.linspace(0, 9, n)) + np.cumsum(rng.normal(0, 0.4, n)) * 0.3
        df["RB=F"] = (df["CL=F"] + crack * 0.95) / 42
        df["HO=F"] = (df["CL=F"] + crack * 1.15) / 42
        self._cache = df
        return df

    def prices(self, tickers, period):
        df = self._universe()
        return df[[t for t in tickers if t in df.columns]]

    def futures_curve(self, today, n):
        spot = float(self._universe()["CL=F"].iloc[-1])
        out = []
        for i, c in enumerate(candidate_cl_contracts(today, n)):
            T = (c["expiry"] - today).days / 365
            p = spot * np.exp(-0.06 * T) + 0.8 * T  # backwardated front, flattening
            out.append({**c, "price": float(round(p, 2))})
        return out

    def option_chains(self, ticker, today):
        from analytics import bs_price
        spot = float(self._universe()[ticker].iloc[-1])
        base = {"USO": 0.34, "XLE": 0.24, "TSLA": 0.58}[ticker]
        chains = []
        d = today
        exps = []
        for k in range(60):
            d = d + timedelta(days=7)
            exps.append(d.strftime("%Y-%m-%d"))
        for e in pick_expiries(exps, today):
            T = ((datetime.strptime(e, "%Y-%m-%d").date() - today).days) / 365
            strikes = np.round(np.linspace(0.6, 1.4, 33) * spot, 1)
            rows_c, rows_p = [], []
            for K in strikes:
                m = np.log(K / spot)
                vol = base * (1 + 0.15 * np.exp(-T * 2)) - 0.18 * m + 0.35 * m * m
                if ticker == "USO":
                    vol = base * (1 - 0.1 * np.sqrt(T)) - 0.10 * m + 0.4 * m * m
                c = bs_price(spot, K, T, 0.042, 0.0, vol, "c")
                p = bs_price(spot, K, T, 0.042, 0.0, vol, "p")
                sp = max(0.01, 0.02 * c)
                rows_c.append({"strike": K, "bid": max(c - sp, 0), "ask": c + sp, "lastPrice": c, "impliedVolatility": vol, "openInterest": 100})
                sp = max(0.01, 0.02 * p)
                rows_p.append({"strike": K, "bid": max(p - sp, 0), "ask": p + sp, "lastPrice": p, "impliedVolatility": vol, "openInterest": 100})
            chains.append((e, pd.DataFrame(rows_c), pd.DataFrame(rows_p)))
        return spot, chains

    def fred(self, series_id):
        rng = self.rng
        end = pd.Timestamp.today().normalize()
        if series_id in ("DGS3MO", "DGS2", "DGS10"):
            idx = pd.bdate_range(end=end, periods=800)
            lvl = {"DGS3MO": 4.0, "DGS2": 3.7, "DGS10": 4.2}[series_id]
            return pd.Series(lvl + np.cumsum(rng.normal(0, 0.03, len(idx))) * 0.3, index=idx)
        if series_id == "GASREGW":
            wti = self._universe()["CL=F"].resample("W-MON").mean()
            return (0.95 + 0.0245 * wti + rng.normal(0, 0.04, len(wti))).round(3)
        if series_id == "APU000072610":
            idx = pd.date_range(end=end, periods=40, freq="MS")
            return pd.Series(0.165 + np.linspace(0, 0.018, len(idx)) + rng.normal(0, 0.002, len(idx)), index=idx)
        raise KeyError(series_id)
