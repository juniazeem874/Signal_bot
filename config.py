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
    "MATICUSDT", "LINKUSDT",
]
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD",
    "USD/CAD", "NZD/USD", "USD/CHF", "EUR/GBP",
]
METAL_PAIRS = ["XAU/USD"]           # Gold — sirf TwelveData
GOLD_PAIR   = "XAU/USD"

ALL_PAIRS = CRYPTO_PAIRS + FOREX_PAIRS + METAL_PAIRS   # 19 total

# Auto-scan ke liye (rotation ke liye same list)
AUTO_SCAN_PAIRS = ALL_PAIRS[:]

# ==================== TIMEFRAMES ====================
CRYPTO_TFS = ["4h", "1h", "15m", "5m", "1m"]
FOREX_TFS  = ["4h", "1h", "15m"]
METAL_TFS  = ["4h", "1h", "15m"]

# ==================== AUTO SCAN ====================
AUTO_SCAN_INTERVAL = 300              # ⭐ 5 minute = 300 seconds
AUTO_SCAN_ENABLED  = True

# Signal management
SIGNAL_EXPIRY_HOURS = 6               # 6h baad signal delete
SIGNAL_COOLDOWN_SECONDS = 6 * 60 * 60 # same pair ka signal 6h tak dobara nahi
SIGNAL_AUTO_DELETE_HOURS = 6

# ==================== SYMBOL ALIASES ====================
SYMBOL_ALIASES = {
    "XAUUSD": "XAU/USD", "GOLD": "XAU/USD", "XAU": "XAU/USD",
    "XAGUSD": "XAG/USD", "SILVER": "XAG/USD",
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT",
    "MATICUSD": "MATICUSDT", "LINKUSD": "LINKUSDT",
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
GEMINI_MODEL      = "gemini-1.5-flash"
GROQ_MODEL        = "llama-3.1-70b-versatile"
GEMINI_BATCH_SIZE = 19               # saare 19 pairs ek Gemini call me

# ==================== STRATEGY ====================
MIN_SCORE_FOR_SIGNAL = 2
SL_ATR_MULTIPLIER    = 1.5
TP_ATR_MULTIPLIER    = 3.0

SL_MULTIPLIERS = {
    "BTCUSDT": 1.5, "ETHUSDT": 1.5, "SOLUSDT": 2.0,
    "BNBUSDT": 1.5, "XRPUSDT": 1.5, "ADAUSDT": 1.5,
    "DOGEUSDT": 1.8, "AVAXUSDT": 1.8,
    "MATICUSDT": 1.8, "LINKUSDT": 1.5,
    "XAU/USD": 1.2, "XAG/USD": 1.3,
    "EUR/USD": 1.0, "GBP/USD": 1.0, "USD/JPY": 1.0,
    "AUD/USD": 1.0, "USD/CAD": 1.0, "NZD/USD": 1.0,
    "USD/CHF": 1.0, "EUR/GBP": 1.0,
}
TP_MULTIPLIERS = {
    "BTCUSDT": 3.0, "ETHUSDT": 3.0, "SOLUSDT": 3.5,
    "BNBUSDT": 3.0, "XRPUSDT": 3.0, "ADAUSDT": 3.0,
    "DOGEUSDT": 3.5, "AVAXUSDT": 3.5,
    "MATICUSDT": 3.5, "LINKUSDT": 3.0,
    "XAU/USD": 2.5, "XAG/USD": 2.5,
    "EUR/USD": 2.0, "GBP/USD": 2.0, "USD/JPY": 2.0,
    "AUD/USD": 2.0, "USD/CAD": 2.0, "NZD/USD": 2.0,
    "USD/CHF": 2.0, "EUR/GBP": 2.0,
}

# ==================== INDICATORS ====================
# AI ko ye saare indicators bhejne hain
INDICATORS_TO_SEND = [
    "rsi", "ema20", "ema50", "ema200",
    "macd", "macd_signal", "atr",
    "volume", "vol_avg", "vol_spike",
    "trend", "bos", "fvg",
]
CANDLES_PER_TF = 200       # har TF ka itna data fetch karo

# ==================== DB ====================
SUBSCRIBERS_DB = "subscribers.db"