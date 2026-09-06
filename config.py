import os

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ---- TwelveData (forex) ----
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# ---- Strategy timeframes ----
ENTRY_INTERVAL_BINANCE = "1h"      # entry timeframe for crypto
TREND_INTERVAL_BINANCE = "4h"      # higher timeframe for trend bias (crypto)

ENTRY_INTERVAL_TWELVEDATA = "1h"   # entry timeframe for forex
TREND_INTERVAL_TWELVEDATA = "4h"   # higher timeframe for trend bias (forex)

CANDLE_LIMIT = 200  # how many candles to pull for indicator calculation

# ---- Signal scoring thresholds ----
MIN_SCORE_FOR_SIGNAL = 3  # out of 4 confluence checks needed to fire BUY/SELL

# ---- Risk management ----
ATR_PERIOD = 14
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIER = 3.0  # gives ~1:2 risk-reward by default

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
