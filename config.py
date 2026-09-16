import os

# ===== API KEYS =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")

# ===== 19 PAIRS (single batch) =====
CRYPTO_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
]
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
    "USD/CAD", "NZD/USD", "USD/CHF", "EUR/GBP",
    "GBP/JPY", "EUR/JPY",
]
GOLD_PAIR = "XAU/USD"   # TwelveData se sirf ye

ALL_PAIRS = CRYPTO_PAIRS + FOREX_PAIRS + [GOLD_PAIR]   # 19 total

# ===== TIMEFRAMES =====
CRYPTO_TFS = ["4h", "1h", "15m", "5m", "1m"]
FOREX_TFS  = ["4h", "1h", "15m"]

# ===== SCHEDULER =====
ANALYSIS_INTERVAL_MINUTES = 5
SIGNAL_EXPIRY_HOURS       = 6      # 6 ghante purane remove
REMOVE_HOLD_SIGNALS       = True   # HOLD bhi remove

# ===== AI BATCHING =====
GEMINI_BATCH_SIZE = 19    # sab ek saath
GEMINI_MODEL      = "gemini-1.5-flash"
GROQ_MODEL        = "llama-3.1-70b-versatile"