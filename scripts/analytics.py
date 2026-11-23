"""Quantitative building blocks: Black-Scholes, implied vol, Greeks, factor
regressions, volatility and VaR. Pure functions, no I/O."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

TRADING_DAYS = 252


# ----------------------------------------------------------- Black-Scholes
def _d1d2(S, K, T, r, q, sig):
    d1 = (math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    return d1, d1 - sig * math.sqrt(T)


def bs_price(S, K, T, r, q, sig, cp="c"):
    d1, d2 = _d1d2(S, K, T, r, q, sig)
    if cp == "c":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def implied_vol(price, S, K, T, r, q, cp="c"):
    """Invert Black-Scholes with Brent's method. Returns None when the quote
    is outside no-arbitrage bounds or the root can't be bracketed."""
    disc_S, disc_K = S * math.exp(-q * T), K * math.exp(-r * T)
    intrinsic = max(disc_S - disc_K, 0) if cp == "c" else max(disc_K - disc_S, 0)
    upper = disc_S if cp == "c" else disc_K
    if not (intrinsic + 1e-6 < price < upper):
        return None
    try:
        return brentq(lambda s: bs_price(S, K, T, r, q, s, cp) - price, 1e-4, 5.0, xtol=1e-6)
    except ValueError:
        return None


def greeks(S, K, T, r, q, sig):
    d1, d2 = _d1d2(S, K, T, r, q, sig)
    pdf = norm.pdf(d1)
    eq, er = math.exp(-q * T), math.exp(-r * T)
    call_theta = (-S * eq * pdf * sig / (2 * math.sqrt(T)) - r * K * er * norm.cdf(d2)
                  + q * S * eq * norm.cdf(d1))
    put_theta = (-S * eq * pdf * sig / (2 * math.sqrt(T)) + r * K * er * norm.cdf(-d2)
                 - q * S * eq * norm.cdf(-d1))
    return {
        "call_price": bs_price(S, K, T, r, q, sig, "c"),
        "put_price": bs_price(S, K, T, r, q, sig, "p"),
        "call_delta": eq * norm.cdf(d1),
        "put_delta": -eq * norm.cdf(-d1),
        "gamma": eq * pdf / (S * sig * math.sqrt(T)),
        "vega_1pt": S * eq * pdf * math.sqrt(T) / 100,      # per 1 vol point
        "call_theta_day": call_theta / 365,
        "put_theta_day": put_theta / 365,
    }


def prob_above(F, K, T, sig):
    """Risk-neutral P(F_T > K) for a lognormal forward: N(d2)."""
    if T <= 0 or sig <= 0:
        return float(F > K)
    d2 = (math.log(F / K) - 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return float(norm.cdf(d2))


def lognormal_quantile(F, T, sig, p):
    z = norm.ppf(p)
    return F * math.exp(-0.5 * sig * sig * T + z * sig * math.sqrt(T))


# --------------------------------------------------------- option surfaces
def _mid(row):
    b, a = row.get("bid", np.nan), row.get("ask", np.nan)
    if pd.notna(b) and pd.notna(a) and b > 0 and a > 0 and a >= b:
        return (a + b) / 2
    lp = row.get("lastPrice", np.nan)
    return lp if pd.notna(lp) and lp > 0 else None


def chain_ivs(S, chains, r, q, today):
    """For each expiry compute our own IVs from mid quotes.
    Returns list of {expiry, T, days, atm_iv, smile:[(moneyness, iv)]}."""
    out = []
    for exp, calls, puts in chains:
        days = (pd.Timestamp(exp).date() - today).days
        T = max(days, 0.5) / 365
        if days < 3:
            continue
        F = S * math.exp((r - q) * T)
        smile, atm_pts = [], []
        for df, cp in ((calls, "c"), (puts, "p")):
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                K = float(row["strike"])
                m = K / F
                if not (0.6 <= m <= 1.4):
                    continue
                px = _mid(row)
                if px is None:
                    continue
                iv = implied_vol(px, S, K, T, r, q, cp)
                if iv is None or not (0.02 < iv < 3):
                    continue
                otm = (cp == "p" and K <= F) or (cp == "c" and K >= F)
                if otm:
                    smile.append((round(m, 4), iv))
                atm_pts.append((abs(m - 1), iv, K))
        if not atm_pts:
            continue
        # ATM IV: average of call & put IVs at the strike(s) closest to forward
        atm_pts.sort()
        kbest = atm_pts[0][2]
        near = [iv for d, iv, K in atm_pts if K == kbest]
        smile.sort()
        out.append({"expiry": exp, "days": days, "T": T,
                    "atm_iv": float(np.mean(near)), "smile": smile})
    return out


def interp_iv(term, T_target):
    """Interpolate ATM IV in total variance (sigma^2 T), flat extrapolation."""
    if not term:
        return None
    Ts = np.array([t["T"] for t in term])
    w = np.array([t["atm_iv"] ** 2 * t["T"] for t in term])
    if T_target <= Ts[0]:
        return float(term[0]["atm_iv"])
    if T_target >= Ts[-1]:
        return float(term[-1]["atm_iv"])
    wt = np.interp(T_target, Ts, w)
    return float(math.sqrt(wt / T_target))


# ------------------------------------------------------- returns & risk
def log_returns(px: pd.DataFrame) -> pd.DataFrame:
    px = px.where(px > 0)
    return np.log(px).diff()


def realized_vol(r: pd.Series, window: int) -> pd.Series:
    return r.rolling(window).std() * math.sqrt(TRADING_DAYS)


def ewma_vol(r: pd.Series, lam: float) -> float:
    r = r.dropna().values
    var = np.var(r[:30]) if len(r) > 30 else np.var(r)
    for x in r:
        var = lam * var + (1 - lam) * x * x
    return float(math.sqrt(var))


def two_factor(y: pd.Series, mkt: pd.Series, oil: pd.Series):
    """OLS y = a + b_m*mkt + b_o*oil + e on aligned daily returns."""
    df = pd.concat([y, mkt, oil], axis=1).dropna()
    if len(df) < 60:
        return None
    Y = df.iloc[:, 0].values
    X = np.column_stack([np.ones(len(df)), df.iloc[:, 1].values, df.iloc[:, 2].values])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    dof = len(Y) - 3
    s2 = resid @ resid / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    r2 = 1 - (resid @ resid) / ((Y - Y.mean()) @ (Y - Y.mean()))
    return {"alpha_ann": float(beta[0] * TRADING_DAYS), "beta_mkt": float(beta[1]),
            "beta_oil": float(beta[2]), "t_oil": float(beta[2] / se[2]),
            "t_mkt": float(beta[1] / se[1]), "r2": float(r2), "n": int(len(Y)),
            "idio_vol": float(math.sqrt(s2 * TRADING_DAYS))}


def rolling_oil_beta(y, mkt, oil, window):
    df = pd.concat([y, mkt, oil], axis=1).dropna()
    df.columns = ["y", "m", "o"]
    out = {}
    vals = df.values
    for i in range(window, len(df) + 1, 5):  # every 5 days keeps the JSON small
        w = vals[i - window:i]
        X = np.column_stack([np.ones(window), w[:, 1], w[:, 2]])
        b, *_ = np.linalg.lstsq(X, w[:, 0], rcond=None)
        out[df.index[i - 1]] = b[2]
    return pd.Series(out)


def var_es(r: pd.Series, lam: float, level=0.95):
    r = r.dropna()
    q = float(np.quantile(r, 1 - level))
    es = float(r[r <= q].mean())
    sig = ewma_vol(r, lam)
    return {"hist_var": -q, "hist_es": -es, "ewma_vol_daily": sig,
            "param_var": float(norm.ppf(level) * sig)}


def percentile_rank(s: pd.Series, x: float) -> float:
    s = s.dropna()
    return float((s < x).mean() * 100) if len(s) else float("nan")
