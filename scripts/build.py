"""Fetch data, run the analytics and write site/data/latest.json.

    python scripts/build.py           # live data (Yahoo Finance + FRED)
    python scripts/build.py --demo    # synthetic data, no network

History that makes the site "accumulate" over time is kept in data/
(curve snapshots + a daily metrics log) and copied into site/data/.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import analytics as A  # noqa: E402
import config as C  # noqa: E402
from sources import DemoSource, LiveSource  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE_DATA = ROOT / "site" / "data"
ERRORS: list[str] = []


def safe(name):
    """Decorator: a failing section is logged and skipped, never fatal."""
    def deco(fn):
        def wrap(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                ERRORS.append(f"{name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                return None
        return wrap
    return deco


def rnd(x, n=4):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def ser(s: pd.Series, n=4):
    s = s.dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [rnd(v, n) for v in s.values]}


# ======================================================================
def main(demo: bool):
    src = DemoSource() if demo else LiveSource()
    today = date.today()
    out = {"meta": {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    "demo": demo,
                    "assumptions": {"mpg": C.MPG, "kwh_per_mile": C.KWH_PER_MILE,
                                    "dcfc_price": C.DCFC_PRICE}}}

    # ------------------------------------------------------------ prices
    all_eq = [C.MARKET] + [t for v in C.BASKETS.values() for t in v] + C.EXTRA
    tickers = list(dict.fromkeys(list(C.COMMODITIES) + all_eq))
    px = src.prices(tickers, C.LOOKBACK)
    px = px.dropna(how="all")
    missing = [t for t in tickers if t not in px.columns or px[t].dropna().empty]
    if missing:
        ERRORS.append(f"prices missing: {', '.join(missing)}")
    rets = A.log_returns(px)
    out["meta"]["asof"] = px.index[-1].strftime("%Y-%m-%d")

    fred = {}
    for sid in C.FRED:
        try:
            fred[sid] = src.fred(sid)
        except Exception as e:  # noqa: BLE001
            ERRORS.append(f"FRED {sid}: {e}")

    r_pct = fred["DGS3MO"].iloc[-1] if "DGS3MO" in fred else 4.0
    r = math.log(1 + r_pct / 100)  # continuous-compounding risk-free rate

    out["rates"] = rates_block(fred)
    out["kpis"] = kpi_block(px)
    out["crack"] = crack_block(px)
    curve = curve_block(src, today, r)
    out["curve"] = curve
    out["options"] = options_block(src, today, r, rets)
    pt = passthrough_block(px, fred)
    out["retail"] = pt
    out["cpm"] = cpm_block(fred, pt)
    out["outlook"] = outlook_block(curve, out["options"], pt, out["cpm"], px)
    out["equities"] = equity_block(px, rets)
    out["vol"] = vol_block(rets)
    out["risk"] = risk_block(rets)

    out["history"] = update_history(out, today)
    out["commentary"], out["watch"] = commentary(out)
    out["meta"]["errors"] = ERRORS

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "latest.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False, default=str))
    print(f"wrote site/data/latest.json  ({len(ERRORS)} non-fatal issues)")
    for e in ERRORS:
        print("  -", e)


# ======================================================================
@safe("rates")
def rates_block(fred):
    g = lambda k: rnd(fred[k].iloc[-1], 3) if k in fred else None  # noqa: E731
    out = {"t3m": g("DGS3MO"), "t2y": g("DGS2"), "t10y": g("DGS10")}
    if out["t2y"] is not None and out["t10y"] is not None:
        out["s2s10_bp"] = rnd((out["t10y"] - out["t2y"]) * 100, 1)
    if "DGS10" in fred and "DGS2" in fred:
        s = (fred["DGS10"] - fred["DGS2"]).dropna()
        out["s2s10_series"] = ser(s[s.index >= s.index[-1] - pd.Timedelta(days=3 * 365)] * 100, 1)
    return out


@safe("kpis")
def kpi_block(px):
    k = {}
    for t in C.COMMODITIES:
        s = px[t].dropna()
        k[t] = {"last": rnd(s.iloc[-1], 3),
                "chg_1d": rnd(s.iloc[-1] / s.iloc[-2] - 1),
                "chg_1m": rnd(s.iloc[-1] / s.iloc[-22] - 1),
                "chg_1y": rnd(s.iloc[-1] / s.iloc[-253] - 1) if len(s) > 253 else None,
                "pctile_3y": rnd(A.percentile_rank(s, s.iloc[-1]), 1)}
    if "BZ=F" in px and "CL=F" in px:
        k["brent_wti"] = rnd(px["BZ=F"].dropna().iloc[-1] - px["CL=F"].dropna().iloc[-1], 2)
    return k


@safe("crack spread")
def crack_block(px):
    df = px[["CL=F", "RB=F", "HO=F"]].dropna()
    crack = (2 * df["RB=F"] * 42 + df["HO=F"] * 42 - 3 * df["CL=F"]) / 3
    gas_crack = df["RB=F"] * 42 - df["CL=F"]
    last = crack.iloc[-1]
    out = {"series": ser(crack, 2), "gas_crack": ser(gas_crack, 2),
           "current": rnd(last, 2), "avg_1y": rnd(crack.iloc[-252:].mean(), 2),
           "pctile_3y": rnd(A.percentile_rank(crack, last), 1),
           "chg_1m": rnd(last - crack.iloc[-22], 2)}
    # refiner sensitivity: VLO daily return on crack change
    if "VLO" in px:
        j = pd.concat([np.log(px["VLO"]).diff(), crack.diff()], axis=1).dropna().iloc[-252:]
        b = np.polyfit(j.iloc[:, 1], j.iloc[:, 0], 1)[0]
        out["vlo_per_dollar_crack_bp"] = rnd(b * 1e4, 1)
        out["vlo_corr"] = rnd(j.corr().iloc[0, 1], 3)
    return out


@safe("futures curve")
def curve_block(src, today, r):
    raw = src.futures_curve(today, C.CURVE_MONTHS)
    if len(raw) < 3:
        raise RuntimeError(f"only {len(raw)} contracts returned")
    pts = [{"label": c["label"], "ticker": c["ticker"], "expiry": str(c["expiry"]),
            "T": rnd((c["expiry"] - today).days / 365), "price": rnd(c["price"], 2)} for c in raw]
    p = [x["price"] for x in pts]
    T = [x["T"] for x in pts]
    i12 = min(11, len(pts) - 1)
    i6 = min(6, len(pts) - 1)
    roll = math.log(p[0] / p[1]) / (T[1] - T[0])
    roll12 = math.log(p[0] / p[i12]) / (T[i12] - T[0])
    m = {"m1": p[0], "m2": p[1], "m7": p[i6], "m12": p[i12],
         "m1_m2": rnd(p[0] - p[1], 2), "m1_m7": rnd(p[0] - p[i6], 2),
         "m1_m12": rnd(p[0] - p[i12], 2), "m1_m12_pct": rnd(p[i12] / p[0] - 1),
         "roll_yield_ann": rnd(roll12),  # +ve = backwardation (long earns roll)
         "roll_yield_front_ann": rnd(roll),
         # cost of carry: F = S e^{(r+u-y)T}  =>  (y-u) = r - ln(F12/F1)/dT
         "conv_yield_net": rnd(r - math.log(p[i12] / p[0]) / (T[i12] - T[0])),
         "rf": rnd(r),
         "structure": "backwardation" if p[i12] < p[0] else "contango"}
    return {"current": pts, "metrics": m}


@safe("options")
def options_block(src, today, r, rets):
    res = []
    for tk, q, label in C.OPTION_UNDERLYINGS:
        try:
            S, chains = src.option_chains(tk, today)
            term = A.chain_ivs(S, chains, r, q, today)
            if not term:
                raise RuntimeError("no usable quotes")
            iv30 = A.interp_iv(term, 30 / 365)
            g = A.greeks(S, S, 30 / 365, r, q, iv30)
            near = min(term, key=lambda t: abs(t["days"] - 30))
            rv20 = None
            if tk in rets:
                rv20 = A.realized_vol(rets[tk], 20).dropna().iloc[-1]
            smile = near["smile"]
            put90 = _smile_at(smile, 0.9)
            call110 = _smile_at(smile, 1.1)
            res.append({
                "ticker": tk, "label": label, "spot": rnd(S, 2),
                "term": [{"days": t["days"], "expiry": t["expiry"], "iv": rnd(t["atm_iv"])} for t in term],
                "smile": {"expiry": near["expiry"], "days": near["days"],
                          "m": [rnd(a) for a, _ in smile], "iv": [rnd(b) for _, b in smile]},
                "iv30": rnd(iv30), "rv20": rnd(rv20),
                "vrp": rnd(iv30 - rv20) if rv20 is not None else None,
                "move_1m": rnd(iv30 * math.sqrt(30 / 365)),
                "skew_90_110": rnd(put90 - call110) if put90 and call110 else None,
                "term_slope": rnd(term[-1]["atm_iv"] - term[0]["atm_iv"]),
                "greeks": {k: rnd(v, 5) for k, v in g.items()},
            })
        except Exception as e:  # noqa: BLE001
            ERRORS.append(f"options {tk}: {e}")
    return res


def _smile_at(smile, m):
    if len(smile) < 3:
        return None
    xs = np.array([a for a, _ in smile])
    ys = np.array([b for _, b in smile])
    if m < xs.min() or m > xs.max():
        return None
    return float(np.interp(m, xs, ys))


@safe("gasoline pass-through")
def passthrough_block(px, fred):
    gas = fred["GASREGW"]
    wti = px["CL=F"].dropna()
    rb = px["RB=F"].dropna()
    # weekly average of WTI and RBOB over the week ending at each retail print
    wk_wti = wti.resample("W-MON").mean()
    wk_rb = rb.resample("W-MON").mean()
    g = gas.copy()
    # align each retail print to the W-MON label (next-or-same Monday)
    g.index = g.index + pd.to_timedelta((7 - g.index.weekday) % 7, unit="D")
    df = pd.concat([g.rename("gas"), wk_wti.rename("wti"), wk_rb.rename("rb")], axis=1).dropna()
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=3 * 365)]
    b, a = np.polyfit(df["wti"], df["gas"], 1)
    pred = a + b * df["wti"]
    r2 = 1 - ((df["gas"] - pred) ** 2).sum() / ((df["gas"] - df["gas"].mean()) ** 2).sum()
    spread = df["gas"] - df["rb"]
    return {"a": rnd(a), "b": rnd(b, 5), "r2": rnd(r2, 3), "n": len(df),
            "cents_per_dollar": rnd(b * 100, 2),
            "retail": ser(df["gas"], 3), "rbob": ser(df["rb"], 3),
            "spread_now": rnd(spread.iloc[-1], 3), "spread_avg": rnd(spread.mean(), 3),
            "gas_last": rnd(gas.iloc[-1], 3), "gas_asof": gas.index[-1].strftime("%Y-%m-%d")}


@safe("cost per mile")
def cpm_block(fred, pt):
    gas = fred["GASREGW"]
    elec = fred["APU000072610"]
    cut = gas.index[-1] - pd.Timedelta(days=3 * 365)
    gas_cpm = gas[gas.index >= cut] / C.MPG
    home = elec[elec.index >= cut] * C.KWH_PER_MILE
    cur = {"gas": rnd(gas.iloc[-1] / C.MPG), "home": rnd(elec.iloc[-1] * C.KWH_PER_MILE),
           "dcfc": rnd(C.DCFC_PRICE * C.KWH_PER_MILE),
           "elec_price": rnd(elec.iloc[-1], 4), "elec_asof": elec.index[-1].strftime("%Y-%m")}
    be = {"gas_vs_dcfc": rnd(C.DCFC_PRICE * C.KWH_PER_MILE * C.MPG, 3),
          "gas_vs_home": rnd(elec.iloc[-1] * C.KWH_PER_MILE * C.MPG, 3)}
    if pt:
        be["wti_vs_dcfc"] = rnd((be["gas_vs_dcfc"] - pt["a"]) / pt["b"], 2)
        be["wti_vs_home"] = rnd((be["gas_vs_home"] - pt["a"]) / pt["b"], 2)
    return {"gas_hist": ser(gas_cpm), "home_hist": ser(home), "current": cur, "breakeven": be,
            "ev_saving_per_10k_home": rnd((cur["gas"] - cur["home"]) * 10000, 0),
            "ev_saving_per_10k_dcfc": rnd((cur["gas"] - cur["dcfc"]) * 10000, 0)}


@safe("12-month outlook")
def outlook_block(curve, options, pt, cpm, px):
    pts = curve["current"]
    Ts = np.array([p["T"] for p in pts])
    Fs = np.array([p["price"] for p in pts])
    uso = next((o for o in options if o["ticker"] == "USO"), None)
    if uso is None:
        raise RuntimeError("needs USO option term structure")
    term = [{"T": t["days"] / 365, "atm_iv": t["iv"]} for t in uso["term"]]
    spot = float(px["CL=F"].dropna().iloc[-1])
    rows = []
    today = pd.Timestamp.today().normalize()
    for k in range(0, C.OUTLOOK_MONTHS + 1):
        T = k / 12
        F = float(np.interp(T, Ts, Fs)) if k else spot
        sig = A.interp_iv(term, max(T, 1 / 52))
        q = {p: (A.lognormal_quantile(F, T, sig, p) if k else F) for p in (0.05, 0.25, 0.5, 0.75, 0.95)}
        rows.append({"month": (today + pd.DateOffset(months=k)).strftime("%b %y"), "T": rnd(T), "fwd": rnd(F, 2),
                     "sigma": rnd(sig), **{f"p{int(p*100):02d}": rnd(v, 2) for p, v in q.items()}})
    F12, sig12 = rows[-1]["fwd"], rows[-1]["sigma"]
    out = {"path": rows, "spot": rnd(spot, 2), "f12": F12, "sigma12": sig12,
           "prob_up20": rnd(A.prob_above(F12, spot * 1.2, 1, sig12)),
           "prob_down20": rnd(1 - A.prob_above(F12, spot * 0.8, 1, sig12)),
           "prob_above_100": rnd(A.prob_above(F12, 100, 1, sig12)),
           "prob_below_50": rnd(1 - A.prob_above(F12, 50, 1, sig12))}
    if pt and cpm:
        be = cpm["breakeven"].get("wti_vs_dcfc")
        if be and be > 0:
            out["prob_dcfc_cheaper_12m"] = rnd(A.prob_above(F12, be, 1, sig12))
        # implied retail gasoline & gas cost per mile 12m out
        to_gas = lambda w: pt["a"] + pt["b"] * w  # noqa: E731
        out["gas_path"] = [{"month": rw["month"], "p05": rnd(to_gas(rw["p05"]) / C.MPG),
                            "p50": rnd(to_gas(rw["p50"]) / C.MPG), "p95": rnd(to_gas(rw["p95"]) / C.MPG),
                            "fwd": rnd(to_gas(rw["fwd"]) / C.MPG)} for rw in rows]
    return out


@safe("equities")
def equity_block(px, rets):
    mkt, oil = rets[C.MARKET], rets["CL=F"]
    W = C.BETA_WINDOW
    factor = []
    basket_rets = {}
    for g, names in C.BASKETS.items():
        avail = [t for t in names if t in rets and rets[t].dropna().size > W]
        # equal-weight, daily-rebalanced basket (simple returns averaged)
        simple = np.exp(rets[avail]) - 1
        basket_rets[g] = np.log1p(simple.mean(axis=1, skipna=True))
        for t in avail:
            f = A.two_factor(rets[t].iloc[-W:], mkt.iloc[-W:], oil.iloc[-W:])
            if f:
                f.update({"ticker": t, "group": g,
                          "ret_1y": rnd(px[t].dropna().iloc[-1] / px[t].dropna().iloc[-253] - 1)})
                factor.append({k: (rnd(v) if isinstance(v, float) else v) for k, v in f.items()})
    bf, rb, perf = [], {}, {}
    start1y = rets.index[-W]
    for g, br in basket_rets.items():
        f = A.two_factor(br.iloc[-W:], mkt.iloc[-W:], oil.iloc[-W:])
        if f:
            f["group"] = g
            f["ret_1y"] = rnd(math.exp(br.loc[start1y:].iloc[1:].sum()) - 1)
            bf.append({k: (rnd(v) if isinstance(v, float) else v) for k, v in f.items()})
        rb[g] = ser(A.rolling_oil_beta(br, mkt, oil, C.ROLLING_BETA_WINDOW), 3)
        perf[g] = ser(100 * np.exp(br.fillna(0).cumsum()), 2)
    perf["S&P 500 (SPY)"] = ser(100 * np.exp(mkt.fillna(0).cumsum()), 2)
    perf["WTI crude"] = ser(100 * np.exp(oil.fillna(0).cumsum()), 2)
    # long EV-makers / short oil-equities spread: the "transition trade"
    if "EV makers" in basket_rets and "Oil & refining" in basket_rets:
        spread = (basket_rets["EV makers"] - basket_rets["Oil & refining"]).fillna(0)
        perf_spread = ser(100 * np.exp(spread.cumsum()), 2)
        f = A.two_factor(spread.iloc[-W:], mkt.iloc[-W:], oil.iloc[-W:])
    else:
        perf_spread, f = None, None
    return {"factor": factor, "basket_factor": bf, "rolling_oil_beta": rb,
            "perf": perf, "transition_spread": perf_spread,
            "transition_factor": {k: rnd(v) for k, v in f.items()} if f else None}


@safe("volatility")
def vol_block(rets):
    names = {"WTI crude": "CL=F", "XLE": "XLE", "TSLA": "TSLA", "SPY": "SPY"}
    series, table = {}, []
    for lbl, t in names.items():
        if t not in rets:
            continue
        rv = A.realized_vol(rets[t], 60).dropna()
        series[lbl] = ser(rv)
        rv20 = A.realized_vol(rets[t], 20).dropna()
        table.append({"name": lbl, "rv20": rnd(rv20.iloc[-1]), "rv60": rnd(rv.iloc[-1]),
                      "pctile_3y": rnd(A.percentile_rank(rv20, rv20.iloc[-1]), 1)})
    corr = {}
    oil = rets["CL=F"]
    for t in ["XLE", "TSLA", "CHPT", "EVGO", "NIO"]:
        if t in rets:
            c = pd.concat([rets[t], oil], axis=1).dropna()
            corr[t] = ser(c.iloc[:, 0].rolling(126).corr(c.iloc[:, 1]).iloc[::5], 3)
    return {"rv60": series, "table": table, "rolling_corr_oil": corr}


@safe("VaR")
def risk_block(rets):
    out = []
    groups = {"WTI crude": rets["CL=F"], "S&P 500 (SPY)": rets[C.MARKET]}
    for g, names in C.BASKETS.items():
        avail = [t for t in names if t in rets]
        groups[g] = np.log1p((np.exp(rets[avail]) - 1).mean(axis=1, skipna=True))
    for name, r in groups.items():
        v = A.var_es(r.iloc[-C.VAR_WINDOW:], C.EWMA_LAMBDA)
        out.append({"name": name, **{k: rnd(x) for k, x in v.items()}})
    return out


# ======================================================================
def update_history(out, today):
    """Append today's snapshot to data/ (committed by the workflow) so charts
    of the curve and key metrics build up over time."""
    DATA.mkdir(exist_ok=True)
    key = out["meta"]["asof"]
    # 1) futures curve snapshots
    ch_path = DATA / "curve_history.json"
    ch = json.loads(ch_path.read_text()) if ch_path.exists() else {}
    if out.get("curve"):
        ch[key] = [{"label": p["label"], "T": p["T"], "price": p["price"]} for p in out["curve"]["current"]]
        ch = dict(sorted(ch.items())[-400:])
        ch_path.write_text(json.dumps(ch, separators=(",", ":")))
    # 2) metrics log
    mh_path = DATA / "metrics_history.csv"
    row = {"date": key}
    k = out.get("kpis") or {}
    row["wti"] = (k.get("CL=F") or {}).get("last")
    row["brent"] = (k.get("BZ=F") or {}).get("last")
    row["crack321"] = (out.get("crack") or {}).get("current")
    cm = (out.get("curve") or {}).get("metrics", {})
    row["m1_m12_pct"] = cm.get("m1_m12_pct")
    row["roll_yield_ann"] = cm.get("roll_yield_ann")
    for o in out.get("options") or []:
        row[f"{o['ticker'].lower()}_iv30"] = o["iv30"]
    cp = (out.get("cpm") or {}).get("current", {})
    row["gas_cpm"], row["ev_home_cpm"] = cp.get("gas"), cp.get("home")
    ol = out.get("outlook") or {}
    row["prob_dcfc_cheaper_12m"] = ol.get("prob_dcfc_cheaper_12m")
    row["wti_f12"] = ol.get("f12")
    bf = {b["group"]: b for b in (out.get("equities") or {}).get("basket_factor", [])}
    row["ev_oil_beta"] = (bf.get("EV makers") or {}).get("beta_oil")
    mh = pd.read_csv(mh_path) if mh_path.exists() else pd.DataFrame()
    mh = pd.concat([mh[mh["date"] != key] if not mh.empty else mh, pd.DataFrame([row])], ignore_index=True)
    mh = mh.sort_values("date")
    mh.to_csv(mh_path, index=False)
    # copy to site and return the part the page needs
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    shutil.copy(ch_path, SITE_DATA / "curve_history.json") if ch_path.exists() else None
    shutil.copy(mh_path, SITE_DATA / "metrics_history.csv")
    snaps = {}
    if ch:
        dates = sorted(ch)
        last = pd.Timestamp(dates[-1])
        for lbl, days in (("1 week ago", 7), ("1 month ago", 30), ("3 months ago", 91)):
            target = last - pd.Timedelta(days=days)
            prior = [d for d in dates if pd.Timestamp(d) <= target]
            if prior:
                snaps[lbl] = {"date": prior[-1], "points": ch[prior[-1]]}
    mh = mh.replace({np.nan: None})
    return {"curve_snapshots": snaps, "metrics": mh.to_dict(orient="list"), "days_tracked": len(mh)}


# ======================================================================
def pct(x, d=0):
    if x is None:
        return "n/a"
    if d == 0 and 0 <= x < 0.005:
        return "&lt;1%"
    if d == 0 and 0.995 < x <= 1:
        return "&gt;99%"
    return f"{x*100:.{d}f}%"


def ordinal(n):
    n = int(round(n))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def commentary(o):
    """Rule-based narrative generated from the numbers, so the words stay
    in sync with the data every day."""
    notes, watch = [], []
    cm = (o.get("curve") or {}).get("metrics")
    k = o.get("kpis") or {}
    wti = (k.get("CL=F") or {}).get("last")
    if cm and wti:
        if cm["structure"] == "backwardation":
            notes.append(
                f"The WTI curve is in <b>backwardation</b>: the 12th contract trades {pct(-cm['m1_m12_pct'],1)} below the front "
                f"(${cm['m1']:.2f} → ${cm['m12']:.2f}). Prompt barrels are scarcer than future barrels, so the market is paying for "
                f"oil today. A fully collateralised long-futures position earns roughly the T-bill rate ({pct(cm['rf'],1)}) plus a "
                f"{pct(cm['roll_yield_ann'],1)} annualised roll yield.")
        else:
            notes.append(
                f"The WTI curve is in <b>contango</b>: the 12th contract is {pct(cm['m1_m12_pct'],1)} above the front "
                f"(${cm['m1']:.2f} → ${cm['m12']:.2f}), signalling ample inventories. Rolling a long position costs "
                f"about {pct(-cm['roll_yield_ann'],1)} a year, which offsets most of the {pct(cm['rf'],1)} T-bill collateral return.")
        notes.append(f"Backing out cost-of-carry, the implied net convenience yield (convenience yield minus storage cost) is "
                     f"<b>{pct(cm['conv_yield_net'],1)}</b> a year: {'positive, meaning holders of physical crude value having it on hand' if cm['conv_yield_net']>0 else 'negative, meaning storage is cheap relative to the value of holding barrels'}.")
    cr = o.get("crack")
    if cr:
        lvl = "rich" if cr["pctile_3y"] > 66 else "thin" if cr["pctile_3y"] < 33 else "middle-of-the-range"
        notes.append(f"The 3-2-1 crack spread is <b>${cr['current']:.2f}/bbl</b> ({ordinal(cr['pctile_3y'])} percentile of 3 years, 1-year avg "
                     f"${cr['avg_1y']:.2f}): refining margins are {lvl}. "
                     + (f"Valero moves about {cr['vlo_per_dollar_crack_bp']:.0f} bp for every $1 change in the crack." if cr.get('vlo_per_dollar_crack_bp') is not None else ""))
    cpm, ol = o.get("cpm"), o.get("outlook")
    if cpm:
        c, be = cpm["current"], cpm["breakeven"]
        notes.append(f"At today's pump price a gasoline car costs <b>{c['gas']*100:.1f}¢/mile</b> to fuel versus <b>{c['home']*100:.1f}¢</b> for an EV "
                     f"charged at home and <b>{c['dcfc']*100:.1f}¢</b> on a public fast charger. Home charging saves about "
                     f"${cpm['ev_saving_per_10k_home']:,.0f} per 10,000 miles; fast charging only beats the pump when gasoline exceeds "
                     f"<b>${be['gas_vs_dcfc']:.2f}/gal</b>" + (f", which maps to roughly <b>${be['wti_vs_dcfc']:.0f} WTI</b> through the pass-through regression." if be.get('wti_vs_dcfc') else "."))
    if ol:
        s = (f"Over the next 12 months, the futures curve prices WTI at <b>${ol['f12']:.2f}</b> and USO options imply "
             f"{pct(ol['sigma12'],0)} volatility, giving a 90% risk-neutral range of ${ol['path'][-1]['p05']:.0f}–${ol['path'][-1]['p95']:.0f}. "
             f"The options market puts the chance of a 20%+ rally at {pct(ol['prob_up20'],0)} and a 20%+ drop at {pct(ol['prob_down20'],0)}.")
        if ol.get("prob_dcfc_cheaper_12m") is not None:
            s += f" Probability that public fast charging is cheaper per mile than gasoline a year from now: <b>{pct(ol['prob_dcfc_cheaper_12m'],0)}</b>."
        notes.append(s)
    eq = o.get("equities")
    if eq and eq.get("basket_factor"):
        bf = {b["group"]: b for b in eq["basket_factor"]}
        ev, ch, oilb = bf.get("EV makers"), bf.get("EV charging"), bf.get("Oil & refining")
        if ev and oilb:
            hedge = ev["beta_oil"] < -0.05 and ev["t_oil"] < -2
            notes.append(
                f"Factor model (1y daily, market + oil): oil equities carry an oil beta of <b>{oilb['beta_oil']:.2f}</b> "
                f"(t={oilb['t_oil']:.1f}); EV makers carry <b>{ev['beta_oil']:.2f}</b> (t={ev['t_oil']:.1f}) and a market beta of "
                f"{ev['beta_mkt']:.2f}" + (f"; charging names {ch['beta_oil']:.2f} (t={ch['t_oil']:.1f})" if ch else "") + ". "
                + ("EV stocks <b>do</b> behave as a short-oil hedge right now." if hedge else
                   "EV stocks do <b>not</b> behave like a short-oil hedge: they trade as high-beta growth equities, so the "
                   "&lsquo;transition trade&rsquo; is mostly a bet on the equity market rather than on oil."))
    opts = {x["ticker"]: x for x in (o.get("options") or [])}
    if "USO" in opts and opts["USO"].get("vrp") is not None:
        u = opts["USO"]
        notes.append(f"Oil options: USO 30-day implied vol is {pct(u['iv30'],1)} vs {pct(u['rv20'],1)} realised "
                     f"(variance risk premium {u['vrp']*100:+.1f} vol pts), an expected ±{pct(u['move_1m'],1)} one-month move. "
                     + (f"The 90/110 skew is {u['skew_90_110']*100:+.1f} pts: {'downside puts are bid' if u['skew_90_110']>0 else 'upside calls are bid, so the market is paying up for supply-shock protection'}." if u.get('skew_90_110') is not None else ""))
    r = o.get("rates") or {}
    if r.get("s2s10_bp") is not None:
        watch.append(f"Rates: 3M T-bill {r['t3m']:.2f}%, 2s10s {r['s2s10_bp']:+.0f} bp. Under cost of carry, higher funding rates "
                     "make holding inventory dearer and push the oil curve toward contango, while rate cuts do the opposite. Easier money also tends to "
                     "lift long-duration, high-beta EV equities more than cash-generating oil majors.")
    if cm:
        watch.append("Curve shape: if the M1–M12 spread flips sign, the market has moved from tight to oversupplied (or the reverse). "
                     "That is the single most informative daily signal on this page.")
    watch.append("Crack spread vs crude: when retail gasoline rises because the crack widened rather than because crude rose, "
                 "refining margins are doing the work. That matters for the EV cost advantage and for refiner equities.")
    if "TSLA" in opts:
        watch.append(f"TSLA implied vol ({pct(opts['TSLA']['iv30'],0)}) is the market's price for EV-sector uncertainty; "
                     "compare it with USO vol to see whether risk is priced in the old energy economy or the new one.")
    return notes, watch


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="use synthetic data (offline test)")
    main(ap.parse_args().demo)
