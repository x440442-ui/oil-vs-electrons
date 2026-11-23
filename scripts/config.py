"""Project configuration: tickers, baskets and the cost-per-mile assumptions.

Edit this file to change the universe or the assumptions; everything else
reads from here.
"""

# ---------------------------------------------------------------- universe
COMMODITIES = {
    "CL=F": "WTI crude (front month, $/bbl)",
    "BZ=F": "Brent crude (front month, $/bbl)",
    "RB=F": "RBOB gasoline (front month, $/gal)",
    "HO=F": "ULSD / heating oil (front month, $/gal)",
}

MARKET = "SPY"

BASKETS = {
    "Oil & refining": ["XLE", "XOM", "CVX", "VLO"],
    "EV makers": ["TSLA", "RIVN", "NIO", "XPEV", "LI"],
    "EV charging": ["CHPT", "EVGO", "BLNK"],
}

# extra single names we want prices for (option underlyings etc.)
EXTRA = ["USO"]

# Option underlyings: (ticker, dividend yield used in Black-Scholes, label)
OPTION_UNDERLYINGS = [
    ("USO", 0.0, "USO (WTI front-month proxy)"),
    ("XLE", 0.032, "XLE (energy equities)"),
    ("TSLA", 0.0, "TSLA (EV bellwether)"),
]

# FRED series (public CSV endpoint, no API key needed)
FRED = {
    "DGS3MO": "3-month Treasury yield (%)",
    "DGS2": "2-year Treasury yield (%)",
    "DGS10": "10-year Treasury yield (%)",
    "GASREGW": "US regular gasoline, retail ($/gal, weekly)",
    "APU000072610": "US electricity, avg price ($/kWh, monthly)",
}

# -------------------------------------------- cost-per-mile assumptions
# All of these are shown on the page so a reader can see and challenge them.
MPG = 28.0                # typical new US gasoline car, real-world combined
KWH_PER_MILE = 0.32       # typical EV incl. ~10% charging losses (~3.1 mi/kWh)
DCFC_PRICE = 0.48         # public DC fast-charging, $/kWh (US network list-price avg)

# ------------------------------------------------------------ analytics
LOOKBACK = "3y"           # price history to pull
BETA_WINDOW = 252         # trading days for the two-factor regression
ROLLING_BETA_WINDOW = 126
VAR_WINDOW = 500
EWMA_LAMBDA = 0.94        # RiskMetrics
CURVE_MONTHS = 20         # how many WTI contracts to try
OUTLOOK_MONTHS = 12
