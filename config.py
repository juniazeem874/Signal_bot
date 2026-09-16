# config.py
import os

# ==================== API KEYS ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")

# ==================== BRANDING ====================
BOT_NAME    = "MJ TRADERS"
BOT_TAGLINE = "Trading Signal Bot"

# ==================== PAIRS ====================
CRYPTO_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT",
]
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
    "USD/CAD", "NZD/USD", "USD/CHF", "EUR/GBP",
]
METAL_PAIRS = ["XAU/USD"]
GOLD_PAIR   = "XAU/USD"

ALL_PAIRS = CRYPTO_PAIRS + FOREX_PAIRS + METAL_PAIRS
AUTO_SCAN_PAIRS = ALL_PAIRS[:]

# ==================== TIMEFRAMES ====================
CRYPTO_TFS = ["4h", "1h", "15m", "5m", "1m"]
FOREX_TFS  = ["4h", "1h", "15m"]
METAL_TFS  = ["1h", "15m"]

# ==================== AUTO SCAN ====================
AUTO_SCAN_INTERVAL  = 300        # 5 min
AUTO_SCAN_ENABLED   = True
SIGNAL_EXPIRY_HOURS = 6
SIGNAL_AUTO_DELETE_HOURS = 6

# ==================== SYMBOL ALIASES ====================
SYMBOL_ALIASES = {
    "XAUUSD": "XAU/USD", "GOLD": "XAU/USD", "XAU": "XAU/USD",
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT",
    "DOTUSD": "DOTUSDT", "LINKUSD": "LINKUSDT",
    "MATICUSD": "DOTUSDT",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "USDCHF": "USD/CHF", "EURGBP": "EUR/GBP",
}


def normalize_symbol(sym: str) -> str:
    if not sym:
        return ""
    s = sym.upper().strip().replace(" ", "")
    if s in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[s]
    no_slash = s.replace("/", "")
    if no_slash in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[no_slash]
    if s in ALL_PAIRS:
        return s
    return s


# ==================== AI ====================
# config.py me ye 2 lines change karo
GEMINI_MODEL = "gemini-2.0-flash"           # ⭐ naya model
GROQ_MODEL   = "openai/gpt-oss-120b"    # ⭐ naya model
GEMINI_BATCH_SIZE = 19

# ==================== STRATEGY ====================
MIN_SCORE_FOR_SIGNAL = 2
SL_ATR_MULTIPLIER    = 1.5
TP_ATR_MULTIPLIER    = 3.0

SL_MULTIPLIERS = {
    "BTCUSDT": 1.5, "ETHUSDT": 1.5, "SOLUSDT": 2.0,
    "BNBUSDT": 1.5, "XRPUSDT": 1.5, "ADAUSDT": 1.5,
    "DOGEUSDT": 1.8, "AVAXUSDT": 1.8,
    "DOTUSDT": 1.8, "LINKUSDT": 1.5,
    "XAU/USD": 1.2,
    "EUR/USD": 1.0, "GBP/USD": 1.0, "USD/JPY": 1.0,
    "AUD/USD": 1.0, "USD/CAD": 1.0, "NZD/USD": 1.0,
    "USD/CHF": 1.0, "EUR/GBP": 1.0,
}
TP_MULTIPLIERS = {
    "BTCUSDT": 3.0, "ETHUSDT": 3.0, "SOLUSDT": 3.5,
    "BNBUSDT": 3.0, "XRPUSDT": 3.0, "ADAUSDT": 3.0,
    "DOGEUSDT": 3.5, "AVAXUSDT": 3.5,
    "DOTUSDT": 3.5, "LINKUSDT": 3.0,
    "XAU/USD": 2.5,
    "EUR/USD": 2.0, "GBP/USD": 2.0, "USD/JPY": 2.0,
    "AUD/USD": 2.0, "USD/CAD": 2.0, "NZD/USD": 2.0,
    "USD/CHF": 2.0, "EUR/GBP": 2.0,
}

# ==================== INDICATORS ====================
CANDLES_PER_TF = 200

# ==================== DB ====================
SUBSCRIBERS_DB = "subscribers.db"