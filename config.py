import os

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ---- TwelveData & AI Keys ----
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # Gemini API Key from Google AI Studio

# ---- PDF Scalping Strategy Timeframes ----
ENTRY_INTERVAL_BINANCE = "1m"
TREND_INTERVAL_BINANCE = "15m"

ENTRY_INTERVAL_TWELVEDATA = "1m"
TREND_INTERVAL_TWELVEDATA = "15m"

CANDLE_LIMIT = 500

# ---- Risk Management ----
MIN_RISK_REWARD = 2.5
SL_BUFFER_PERCENT = 0.0005
ATR_PERIOD = 14

# ---- Pairs List ----
CRYPTO_QUOTE_ASSET = "USDT"
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "XAU/USD"
]

# --- AUTO SIGNAL SCANNER SETTINGS ---
AUTO_SCAN_ENABLED = True
AUTO_SCAN_INTERVAL = 60

raw_chat_ids = os.getenv("AUTO_SIGNAL_CHAT_ID", "")
AUTO_SIGNAL_CHAT_IDS = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

AUTO_SCAN_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "XAU/USD", "EUR/USD", "GBP/USD",
    "USD/JPY", "USD/CAD", "AUD/USD"
]
