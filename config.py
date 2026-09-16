# config.py
import os

# ==================== API KEYS ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")

# ==================== CHAT IDs ====================
_raw_ids = os.getenv("TELEGRAM_CHAT_IDS", "") or os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = [
    int(cid.strip()) for cid in _raw_ids.split(",") if cid.strip().lstrip("-").isdigit()
]
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else ""

# ==================== BOT BRANDING ====================
BOT_NAME = "MJ TRADING"
BOT_TAGLINE = "Trading Signal Bot"

# ==================== PAIRS ====================
CRYPTO_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "MATICUSDT", "LINKUSDT",
]
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
    "USD/CAD", "NZD/USD", "USD/CHF", "EUR/GBP",
]
GOLD_PAIR = "XAU/USD"
ALL_PAIRS = CRYPTO_PAIRS + FOREX_PAIRS + [GOLD_PAIR]

# ==================== SYMBOL ALIASES ====================
SYMBOL_ALIASES = {
    # Gold
    "XAUUSD": "XAU/USD", "GOLD": "XAU/USD", "XAU": "XAU/USD",
    # Crypto USD → USDT
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT",
    "MATICUSD": "MATICUSDT", "LINKUSD": "LINKUSDT",
    # Forex no-slash
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "USDCHF": "USD/CHF", "EURGBP": "EUR/GBP",
}


def normalize_symbol(sym: str) -> str:
    """User input → internal symbol."""
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


# ==================== TIMEFRAMES ====================
CRYPTO_TFS = ["4h", "1h", "15m", "5m", "1m"]
FOREX_TFS  = ["4h", "1h", "15m"]

# ==================== SCHEDULER ====================
ANALYSIS_INTERVAL_MINUTES = 60
SIGNAL_EXPIRY_HOURS       = 6

# ==================== AI ====================
GEMINI_MODEL      = "gemini-1.5-flash"
GROQ_MODEL        = "llama-3.1-70b-versatile"
GEMINI_BATCH_SIZE = 19

# ==================== STRATEGY ====================
MIN_SCORE_FOR_SIGNAL = 2
SL_ATR_MULTIPLIER    = 1.5
TP_ATR_MULTIPLIER    = 3.0
SL_MULTIPLIERS = {
    "BTCUSDT": 1.5, "ETHUSDT": 1.5, "SOLUSDT": 2.0,
    "XAU/USD": 1.2, "EUR/USD": 1.0, "GBP/USD": 1.0, "USD/JPY": 1.0,
}
TP_MULTIPLIERS = {
    "BTCUSDT": 3.0, "ETHUSDT": 3.0, "SOLUSDT": 3.5,
    "XAU/USD": 2.5, "EUR/USD": 2.0, "GBP/USD": 2.0, "USD/JPY": 2.0,
}

# ==================== DB ====================
SUBSCRIBERS_DB = "subscribers.db"