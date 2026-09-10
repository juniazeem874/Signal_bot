import os

# ---- Telegram & API Keys ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "goldapi-251c13464305698003f71af084a5c3a9-io")

# ---- Timeframes ----
ENTRY_INTERVAL_BINANCE = "1m"
TREND_INTERVAL_BINANCE = "15m"
ENTRY_INTERVAL_TWELVEDATA = "1min"
TREND_INTERVAL_TWELVEDATA = "15min"
CANDLE_LIMIT = 500

# ---- ACCURACY & RISK ACCORDING TO SCALPING ----
MIN_RISK_REWARD = 1.8         # Realistic TP target for 1m scalping
ATR_SL_MULTIPLIER = 1.5       # ATR buffer to stop premature SL hits
MIN_AI_CONFIDENCE = 85        # Minimum 85% AI confidence required for BUY/SELL
ATR_PERIOD = 14

# ---- MAX ALLOWED SPREAD (In Pips) ----
MAX_ALLOWED_SPREAD = {
    "EUR/USD": 1.5,
    "GBP/USD": 2.0,
    "USD/JPY": 2.0,
    "USD/CAD": 2.0,
    "AUD/USD": 2.0,
    "XAU/USD": 3.5,
    "BTCUSDT": 5.0,
    "ETHUSDT": 3.0,
    "SOLUSDT": 3.0
}

PIP_SIZE = {
    "EUR/USD": 0.0001,
    "GBP/USD": 0.0001,
    "USD/JPY": 0.01,
    "USD/CAD": 0.0001,
    "AUD/USD": 0.0001,
    "XAU/USD": 0.1,
    "BTCUSDT": 1.0,
    "ETHUSDT": 0.1,
    "SOLUSDT": 0.01
}

# ---- Pairs List ----
CRYPTO_QUOTE_ASSET = "USDT"
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD", "XAU/USD"
]

# ---- Auto Scan Settings ----
AUTO_SCAN_ENABLED = True
AUTO_SCAN_INTERVAL = 60

raw_chat_ids = os.getenv("AUTO_SIGNAL_CHAT_ID", "")
AUTO_SIGNAL_CHAT_IDS = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

AUTO_SCAN_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "XAU/USD", "EUR/USD", "GBP/USD",
    "USD/JPY", "USD/CAD", "AUD/USD"
]
