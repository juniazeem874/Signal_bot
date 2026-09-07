import os

# ---- Telegram ----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ---- TwelveData (forex) ----
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# ---- PDF Scalping Strategy Timeframes ----
ENTRY_INTERVAL_BINANCE = "1m"      # LTF Execution (1-Minute)
TREND_INTERVAL_BINANCE = "15m"     # HTF Anchor (15-Minute)

ENTRY_INTERVAL_TWELVEDATA = "1m"   # LTF Execution
TREND_INTERVAL_TWELVEDATA = "15m"  # HTF Anchor

CANDLE_LIMIT = 500  # Pull candles for VWAP & Fibonacci calculation

# ---- Signal Scoring Thresholds ----
MIN_SCORE_FOR_SIGNAL = 3  # Out of 4 confluence checks needed

# ---- Fibonacci Golden Pocket Matrix ----
FIB_GOLDEN_POCKET_LOW = 0.618
FIB_GOLDEN_POCKET_HIGH = 0.705

# ---- Volume Confirmation (PDF Rules) ----
VOL_SMA_PERIOD = 5
VOL_SPIKE_MULTIPLIER = 1.5  # Must be 1.5x preceding 5-candle SMA

# ---- Risk Management (PDF Rules) ----
MIN_RISK_REWARD = 2.5       # Baseline 1:2.5 RR
BREAKEVEN_RR = 1.5          # RR to move SL to Breakeven
SL_BUFFER_PERCENT = 0.0005  # Extra buffer beyond Fib 1.0 level (~2 pips equivalent)
ATR_PERIOD = 14

# ---- Crypto Pair List (Binance) ----
CRYPTO_QUOTE_ASSET = "USDT"
CRYPTO_TOP_N = 30

# ---- Forex Pair List (TwelveData) ----
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD",
    "GBP/JPY", "GBP/CHF", "GBP/AUD", "GBP/CAD",
    "AUD/JPY", "AUD/NZD", "AUD/CAD", "CAD/JPY", "CHF/JPY", "NZD/JPY",
    "XAU/USD", "XAG/USD",
]
