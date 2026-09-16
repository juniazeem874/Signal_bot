# config.py
import os

# ==================== API KEYS ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")   # ⭐ YE ADD KARO
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

# ==================== TIMEFRAMES ====================
CRYPTO_TFS = ["4h", "1h", "15m", "5m", "1m"]
FOREX_TFS  = ["4h", "1h", "15m"]
METAL_TFS  = ["1h", "15m"]

# ==================== AUTO SCAN ====================
AUTO_SCAN_INTERVAL = 300
AUTO_SCAN_ENABLED  = True
SIGNAL_EXPIRY_HOURS = 6
SIGNAL_AUTO_DELETE_HOURS = 6

# ==================== SCHEDULE (PKT = UTC + 5) ====================
BOT_START_HOUR_UTC = 3
BOT_END_HOUR_UTC   = 20
WEEKEND_CRYPTO_ONLY = True

# ==================== AI (UPDATED MODELS) ====================
GEMINI_MODEL      = "gemini-2.5-flash"
GROQ_MODEL        = "openai/gpt-oss-120b"
GEMINI_BATCH_SIZE = 10

# ==================== STRATEGY ====================
MIN_SCORE_FOR_SIGNAL = 2
SL_ATR_MULTIPLIER    = 1.5
TP_ATR_MULTIPLIER    = 3.0

# ==================== INDICATORS ====================
CANDLES_PER_TF = 200

# ==================== JSON STORAGE ====================
DATA_DIR     = "data"
MARKET_JSON  = "market_data.json"
SIGNALS_JSON = "ai_signals.json"

# ==================== SYMBOL ALIASES ====================
SYMBOL_ALIASES = {
    "XAUUSD": "XAU/USD", "GOLD": "XAU/USD", "XAU": "XAU/USD",
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT",
    "BNBUSD": "BNBUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT",
    "DOTUSD": "DOTUSDT", "LINKUSD": "LINKUSDT",
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD",
    "USDCHF": "USD/CHF", "EURGBP": "EUR/GBP",
}


def normalize_symbol(sym):
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