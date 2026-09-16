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
SYSTEM_PROMPT = f"""You are a professional multi-asset trading analyst for {BOT_NAME} signals channel.

You receive a JSON array of assets with multi-timeframe indicators AND Fibonacci retracement data.

For each asset you have:
  - Multi-TF data: RSI, EMA20/50/200, MACD, ATR, Volume, Volume spike, Trend, BOS, FVG
  - Fibonacci retracement: levels (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0), golden zone, current zone

For EACH asset return a JSON object with EXACT keys:
  symbol         : string
  signal         : "BUY" | "SELL" | "HOLD"
  confidence     : integer 0-100
  entry          : number (current price from smallest TF close) — NEVER 0
  stop_loss      : number (ATR-based or beyond nearest Fib level)
  take_profit    : number (1:2 risk-reward minimum)
  reason         : string with 3 sentences separated by " • "
  fib_analysis   : string — how Fibonacci influences this trade
  top_indicators : array of 3 strings

CRITICAL RULES:
1. entry MUST always be > 0. Use current close. NEVER 0.
2. Use Fibonacci:
   - Price IN_GOLDEN_ZONE + trend up → strong BUY
   - Price at 0.5/0.618 rejection in uptrend → BUY
   - Price at 0.5/0.618 rejection in downtrend → SELL
   - Price breaks 0.786 → continuation
3. Confluence: BOS + FVG + Volume spike + Fib alignment → high confidence.
4. If TFs conflict AND no Fib alignment → HOLD, low confidence.
5. Bias towards actionable BUY/SELL when Fib + trend align.
6. SL should respect nearest Fibonacci level.
7. Return ONLY valid JSON array, no markdown fences, no explanation.
"""


# ==================== PARSER ====================
def _parse_json(text):
    text = text.strip()
    for fence in ("```json", "```"):
        text = text.removeprefix(fence)
    text = text.removesuffix("```").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "signals" in data:
                return data["signals"]
            if "symbol" in data:
                return [data]
            for v in data.values():
                if isinstance(v, list):
                    return v
        return data if isinstance(data, list) else []
    except Exception as e:
        log.error(f"JSON parse fail: {e}\nRaw: {text[:400]}")
        return []


# ==================== AI CALLS ====================
def _call_gemini(batch):
    if gemini_model is None:
        raise RuntimeError("Gemini not configured")
    prompt = SYSTEM_PROMPT + "\n\nDATA:\n" + json.dumps(batch, separators=(",", ":"))
    log.info(f"📡 Gemini request: {len(prompt)} chars")
    resp = gemini_model.generate_content(prompt)
    return _parse_json(resp.text)


def _call_groq(batch):
    if groq_client is None:
        raise RuntimeError("Groq not configured")
    resp = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": json.dumps(batch, separators=(",", ":"))},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


def _fallback_hold(symbol, reason, last_price=0.0):
    return {
        "symbol": symbol, "signal": "HOLD", "confidence": 0,
        "reason": f"{reason}. • No confluence detected. • Waiting for clearer setup.",
        "entry": last_price, "stop_loss": 0, "take_profit": 0,
        "fib_analysis": "Unavailable",
        "top_indicators": [],
    }


# ==================== MASTER ====================
def analyze_all_pairs(tf_data_per_symbol):
    """Bundles → chunks → AI (Gemini primary, Groq fallback)."""
    bundles = []
    for sym, tf_data in tf_data_per_symbol.items():
        b = build_indicator_bundle(sym, tf_data)
        if b["timeframes"]:
            bundles.append(b)

    log.info(f"📦 Bundles ready: {len(bundles)} pairs (with Fibonacci)")

    chunks = [bundles[i:i+GEMINI_BATCH_SIZE] for i in range(0, len(bundles), GEMINI_BATCH_SIZE)]
    log.info(f"🔪 {len(chunks)} chunks of {GEMINI_BATCH_SIZE}")

    results = []
    for idx, chunk in enumerate(chunks, 1):
        log.info(f"→ Chunk {idx}/{len(chunks)} ({len(chunk)} pairs)")

        out = None
        try:
            out = _call_gemini(chunk)
            if out:
                log.info(f"✅ Gemini OK chunk {idx}")
        except Exception as e:
            log.warning(f"⚠️ Gemini failed chunk {idx}: {e}")

        if not out:
            try:
                log.info(f"→ Groq fallback chunk {idx}")
                out = _call_groq(chunk)
                if out:
                    log.info(f"✅ Groq OK chunk {idx}")
            except Exception as e:
                log.error(f"❌ Groq failed chunk {idx}: {e}")

        if not out:
            for b in chunk:
                results.append(_fallback_hold(b["symbol"], "AI unavailable",
                                              _last_price_from_bundle(b)))
        else:
            results.extend(out)

        time.sleep(1.2)

    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            results.append(_fallback_hold(b["symbol"], "No AI output",
                                          _last_price_from_bundle(b)))

    return results