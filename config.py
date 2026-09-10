import os

# ---- Telegram & API Keys ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
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
    "XAU/USD": 0.35,   # $0.35 Gold Spread Buffer
    "EUR/USD": 0.00015, # 1.5 Pips
    "GBP/USD": 0.00020, # 2.0 Pips
    "USD/JPY": 0.020,   # 2.0 Pips
    "USD/CAD": 0.00020,
    "AUD/USD": 0.00020,
    "BTCUSDT": 10.0,    # $10 Buffer
    "ETHUSDT": 1.5,
    "SOLUSDT": 0.10
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
AUTO_SCAN_INTERVAL = 60  # Scan every 60 seconds (1 minute) for live active trade tracking

raw_chat_ids = os.getenv("AUTO_SIGNAL_CHAT_ID", "")
AUTO_SIGNAL_CHAT_IDS = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]

AUTO_SCAN_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "XAU/USD", "EUR/USD", "GBP/USD",
    "USD/JPY", "USD/CAD", "AUD/USD"
]
