import os

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ---- TwelveData (forex) ----
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# ---- Multi-timeframe strategy (top-down analysis) ----
# Ordered from Highest Time Frame (HTF, sets the trend bias) down to the
# entry timeframe (last in the list = where BOS/FVG/Fibonacci/volume are
# checked for the actual trigger). This mirrors how institutional/SMC
# traders actually work: higher frames set direction, lower frames time
# the entry.
#
# Crypto (Binance) has no meaningful rate limit for this, so it gets the
# full stack down to 1m. Forex (TwelveData free tier = 800 requests/day,
# 8/min) stops at 15m — adding 5m/1m would multiply API calls per signal
# check and burn through the daily quota fast.
MTF_STACK_CRYPTO = ["4h", "1h", "15m", "5m", "1m"]
MTF_STACK_FOREX = ["4h", "1h", "15m"]

# Out of 3 possible entry-timeframe checks (BOS, FVG/Fibonacci zone, Volume),
# how many must agree — on top of the higher-timeframe stack already having
# to align — before a BUY/SELL fires.
MTF_MIN_ENTRY_SCORE = 2

CANDLE_LIMIT = 200  # how many candles to pull for indicator calculation

# ---- Risk management ----
ATR_PERIOD = 14
SL_ATR_MULTIPLIER = 1.5   # default, used for any symbol not listed below
TP_ATR_MULTIPLIER = 3.0   # default, used for any symbol not listed below

# Per-asset overrides: some instruments (gold, BTC) whip around more than
# altcoins/majors on the same timeframe, so a stop that's too tight just gets
# clipped by noise before the real move happens. These starting points widen
# the stop (and target) for those symbols — re-run /backtest after any change
# here to confirm it actually helped, don't assume it did.
ASSET_RISK_OVERRIDES = {
    "BTCUSDT": {"sl_mult": 2.2, "tp_mult": 3.5},
    "XAU/USD": {"sl_mult": 2.5, "tp_mult": 4.0},
    "XAG/USD": {"sl_mult": 2.5, "tp_mult": 4.0},
    "GBP/USD": {"sl_mult": 2.0, "tp_mult": 3.5},  # "Cable" — sharper moves than EUR/USD, tight SL got stopped out too often (20.4% WR at default 1.5x)
}


def get_risk_params(symbol: str):
    """Returns (sl_multiplier, tp_multiplier) for a symbol, falling back to
    the defaults above if it has no specific override."""
    if symbol:
        override = ASSET_RISK_OVERRIDES.get(symbol.upper())
        if override:
            return override["sl_mult"], override["tp_mult"]
    return SL_ATR_MULTIPLIER, TP_ATR_MULTIPLIER

# ---- Crypto pair list (Binance) ----
# "All pairs" via Binance is technically possible (1000+), but for usability
# we show the top pairs by 24h volume dynamically, plus support typing any
# symbol directly (e.g. /signal DOGEUSDT).
CRYPTO_QUOTE_ASSET = "USDT"
CRYPTO_TOP_N = 30

# ---- Forex pair list (TwelveData free tier) ----
# TwelveData free tier = 800 requests/day, 8/min. "All" forex pairs would
# blow through that fast if polled continuously, so we ship a comprehensive
# major + minor + metals list here, and also support typing any symbol
# directly (e.g. /signal USDCHF).
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD",
    "GBP/JPY", "GBP/CHF", "GBP/AUD", "GBP/CAD",
    "AUD/JPY", "AUD/NZD", "AUD/CAD", "CAD/JPY", "CHF/JPY", "NZD/JPY",
    "XAU/USD", "XAG/USD",
]
