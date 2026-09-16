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
from indicators import add_indicators

log = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(GEMINI_MODEL)
else:
    gemini_model = None

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ================= BUNDLE =================
def build_indicator_bundle(symbol, tf_data):
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
            bundle["timeframes"][tf] = {
                "close":     round(float(last["close"]), 5),
                "rsi":       round(float(last.get("rsi") or 0), 2),
                "ema20":     round(float(last.get("ema20") or 0), 5),
                "ema50":     round(float(last.get("ema50") or 0), 5),
                "ema200":    round(float(last.get("ema200") or 0), 5),
                "macd":      round(float(last.get("macd") or 0), 5),
                "macd_sig":  round(float(last.get("macd_signal") or 0), 5),
                "atr":       round(float(last.get("atr") or 0), 5),
                "volume":    round(float(last.get("volume") or 0), 2),
                "vol_avg":   round(vol_avg, 2),
                "vol_spike": bool(last.get("vol_spike", False)),
                "trend":     str(last.get("trend", "NA")),
                "bos":       bool(last.get("bos", False)),
                "fvg":       bool(last.get("fvg", False)),
            }
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


# ================= PROMPT =================
SYSTEM_PROMPT = f"""You are a professional trader bot for {BOT_NAME} signals channel.
Analyze multi-timeframe indicators and give an actionable BUY/SELL/HOLD signal.

BIAS TOWARDS ACTION:
- Higher TF trend up + lower TF bullish hint → BUY
- Higher TF trend down + lower TF bearish hint → SELL
- RSI < 40 with BOS/FVG → SELL
- RSI > 60 with BOS/FVG → BUY
- Volume spike confirms direction → increase confidence
- Only HOLD if EVERYTHING is sideways/neutral (rare)
- Confidence 60-90 for actionable, 20-40 for HOLD

For EACH asset return JSON object with EXACT keys:
  symbol         : string
  signal         : "BUY" | "SELL" | "HOLD"
  confidence     : integer 0-100
  entry          : number — current price. NEVER 0.
  stop_loss      : number — ATR-based. 0 only if HOLD.
  reason         : string with 3 sentences separated by " • "
  top_indicators : array of 3 strings

Rules:
1. entry MUST always be > 0.
2. Prefer BUY/SELL when trend + momentum align.
3. Return ONLY valid JSON array, no markdown.
"""

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


def _call_gemini(batch):
    if gemini_model is None:
        raise RuntimeError("Gemini not configured")
    prompt = SYSTEM_PROMPT + "\n\nDATA:\n" + json.dumps(batch, separators=(",", ":"))
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
        "entry": last_price, "stop_loss": 0,
        "top_indicators": [],
    }


# ================= MASTER =================
def analyze_all_pairs(tf_data_per_symbol):
    bundles = []
    for sym, tf_data in tf_data_per_symbol.items():
        b = build_indicator_bundle(sym, tf_data)
        if b["timeframes"]:
            bundles.append(b)

    log.info(f"Bundles ready: {len(bundles)} pairs")

    results = []
    for i in range(0, len(bundles), GEMINI_BATCH_SIZE):
        batch = bundles[i : i + GEMINI_BATCH_SIZE]
        try:
            log.info(f"→ Gemini batch ({len(batch)} pairs)")
            out = _call_gemini(batch)
            if out:
                results.extend(out)
                continue
            raise RuntimeError("Gemini empty")
        except Exception as e:
            log.warning(f"Gemini failed → Groq: {e}")
            try:
                out = _call_groq(batch)
                if out:
                    results.extend(out)
                    continue
                raise RuntimeError("Groq empty")
            except Exception as e2:
                log.error(f"Groq failed too: {e2}")
                for b in batch:
                    results.append(_fallback_hold(b["symbol"], "AI unavailable", _last_price_from_bundle(b)))
        time.sleep(1.2)

    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            results.append(_fallback_hold(b["symbol"], "No AI output", _last_price_from_bundle(b)))

    return results