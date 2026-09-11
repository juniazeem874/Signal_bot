import os

# ---- Telegram & API Keys ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")  # gemini-1.5-flash was retired by Google — always returns 404 now
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "goldapi-251c13464305698003f71af084a5c3a9-io")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # free key from finnhub.io — powers real economic-calendar news

# ---- Timeframes ----
ENTRY_INTERVAL_BINANCE = "1m"
TREND_INTERVAL_BINANCE = "15m"
ENTRY_INTERVAL_TWELVEDATA = "1min"
TREND_INTERVAL_TWELVEDATA = "15min"
CANDLE_LIMIT = 500

# ---- ACCURACY & RISK ACCORDING TO SCALPING ----
MIN_RISK_REWARD = 1.3         # 1m scalping ke liye realistic TP
MIN_AI_CONFIDENCE = 70        # Lowered from 85% to 70% so more high-probability trades trigger
ATR_PERIOD = 14


# ---- EXNESS SPREAD BUFFER PADDING (To avoid early SL hits on Exness) ----
EXNESS_SPREAD_BUFFERS = {
    "XAU/USD": 0.35,     # $0.35 Gold Spread Buffer
    "XAG/USD": 0.03,     # Silver Spread Buffer
    "EUR/USD": 0.00015,  # 1.5 Pips
    "GBP/USD": 0.00020,  # 2.0 Pips
    "USD/JPY": 0.020,    # 2.0 Pips
    "USD/CAD": 0.00020,
    "USD/CHF": 0.00020,
    "AUD/USD": 0.00020,
    "NZD/USD": 0.00020,
    "EUR/GBP": 0.00015,
    "EUR/JPY": 0.020,
    "GBP/JPY": 0.025,
    "BTCUSDT": 10.0,     # $10 Buffer
    "ETHUSDT": 1.5,
    "BNBUSDT": 0.5,
    "SOLUSDT": 0.10,
    "XRPUSDT": 0.002,
    "ADAUSDT": 0.002,
    "DOGEUSDT": 0.0005,
}

PIP_SIZE = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "USD/CAD": 0.0001,
    "USD/CHF": 0.0001,
    "AUD/USD": 0.0001,
    "NZD/USD": 0.0001,
    "EUR/GBP": 0.0001,
    "EUR/JPY": 0.01,
    "GBP/JPY": 0.01,
    "XAU/USD": 0.1,
    "XAG/USD": 0.01,
    "BTCUSDT": 1.0,
    "ETHUSDT": 0.1,
    "BNBUSDT": 0.1,
    "SOLUSDT": 0.01,
    "XRPUSDT": 0.0001,
    "ADAUSDT": 0.0001,
    "DOGEUSDT": 0.00001,
}

# ---- Pairs List (also drives the /start pair-picker menu) ----
CRYPTO_QUOTE_ASSET = "USDT"

# Only well-known/liquid pairs — not Binance's full 1000+ pair list.
CRYPTO_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "GBP/JPY"
]

METAL_PAIRS = ["XAU/USD", "XAG/USD"]

# ---- Auto Scan Settings ----
AUTO_SCAN_ENABLED = True
AUTO_SCAN_INTERVAL = 60  # Scan every 60 seconds (1 minute) for live active trade tracking

raw_chat_ids = os.getenv("AUTO_SIGNAL_CHAT_ID", "")
AUTO_SIGNAL_CHAT_IDS = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

# More forex/metal pairs = more TwelveData calls per scan cycle. Free tier is
# 800/day & 8/min — this list already exceeds 8/min, so most cycles fall
# through to the Yahoo Finance fallback automatically. Upgrade TwelveData's
# plan for full-quota coverage on every pair every cycle.
AUTO_SCAN_PAIRS = CRYPTO_PAIRS + METAL_PAIRS + FOREX_PAIRS
