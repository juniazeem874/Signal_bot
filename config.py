import os

# ---- Telegram & API Keys ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ---- Timeframes ----
ENTRY_INTERVAL_BINANCE = "1m"
TREND_INTERVAL_BINANCE = "15m"
ENTRY_INTERVAL_TWELVEDATA = "1m"
TREND_INTERVAL_TWELVEDATA = "15m"
CANDLE_LIMIT = 500

# ---- ACCURACY & RISK ACCORDING TO SCALPING ----
MIN_RISK_REWARD = 1.8         # Realistic TP target for 1m scalping
ATR_SL_MULTIPLIER = 1.5       # ATR buffer to stop premature SL hits
MIN_AI_CONFIDENCE = 80        # Minimum 80% AI confidence required for BUY/SELL
ATR_PERIOD = 14

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
