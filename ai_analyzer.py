# ai_analyzer.py
import json
import time
import logging
import google.generativeai as genai
from groq import Groq

from config import (
    GEMINI_API_KEY, GROQ_API_KEY,
    GEMINI_MODEL, GROQ_MODEL, GEMINI_BATCH_SIZE,
    BOT_NAME,
)
from indicators import add_indicators, fibonacci_retracement

log = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(GEMINI_MODEL)
else:
    gemini_model = None

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ==================== BUNDLE BUILDER ====================
def build_indicator_bundle(symbol, tf_data):
    """Har pair ka compact bundle with Fibonacci."""
    bundle = {"symbol": symbol, "timeframes": {}}

    for tf, df in tf_data.items():
        if df is None or df.empty:
            continue
        try:
            if "rsi" not in df.columns:
                df = add_indicators(df)
            if df.empty:
                continue
            last = df.iloc[-1]
            vol_avg = float(df["volume"].tail(20).mean() or 1)

            tf_out = {
                "close":     round(float(last["close"]), 6),
                "rsi":       round(float(last.get("rsi") or 0), 2),
                "ema20":     round(float(last.get("ema20") or 0), 6),
                "ema50":     round(float(last.get("ema50") or 0), 6),
                "ema200":    round(float(last.get("ema200") or 0), 6),
                "macd":      round(float(last.get("macd") or 0), 6),
                "macd_sig":  round(float(last.get("macd_signal") or 0), 6),
                "atr":       round(float(last.get("atr") or 0), 6),
                "volume":    round(float(last.get("volume") or 0), 2),
                "vol_avg":   round(vol_avg, 2),
                "vol_spike": bool(last.get("vol_spike", False)),
                "trend":     str(last.get("trend", "NA")),
                "bos":       bool(last.get("bos", False)),
                "fvg":       bool(last.get("fvg", False)),
            }

            # Fibonacci add karo
            fib = fibonacci_retracement(df, lookback=50)
            if fib:
                tf_out["fibonacci"] = {
                    "direction":     fib["direction"],
                    "swing_high":    fib["swing_high"],
                    "swing_low":     fib["swing_low"],
                    "levels":        fib["levels"],
                    "golden_zone":   fib["golden_zone"],
                    "current_zone":  fib["current_zone"],
                    "nearest_level": fib["nearest_level"],
                }

            bundle["timeframes"][tf] = tf_out
        except Exception as e:
            log.warning(f"bundle {symbol} {tf}: {e}")

    return bundle


def _last_price_from_bundle(b):
    tfs = list(b.get("timeframes", {}).keys())
    for tf in reversed(tfs):
        c = b["timeframes"][tf].get("close")
        if c:
            return float(c)
    return 0.0


# ==================== PROMPT ====================
SYSTEM_PROMPT = f