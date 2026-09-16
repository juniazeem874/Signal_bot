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


# ================= INDICATOR BUNDLE =================
def build_indicator_bundle(symbol: str, tf_data: dict) -> dict:
    """Compact last-row summary per TF — token optimize."""
    bundle = {"symbol": symbol, "timeframes": {}}
    for tf, df in tf_data.items():
        if df is None or df.empty:
            continue
        try:
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


# ================= PROMPT (MJ TRADING STYLE) =================
SYSTEM_PROMPT = f"""You are a professional multi-asset trading analyst for a Telegram signals bot named {BOT_NAME}.
You receive a JSON array of assets (crypto, forex, gold) with multi-timeframe indicator data:
RSI, EMA20/50/200, MACD, ATR, Volume + volume spike, Trend, BOS (break of structure), FVG (fair value gap).

For EACH asset return a JSON object with these EXACT keys:
  symbol           : string (same as input)
  signal           : "BUY" | "SELL" | "HOLD"
  confidence       : integer 0-100
  entry            : number (current price)
  stop_loss        : number (ATR-based, on correct side)
  reason           : string with EXACTLY 3 short bullet points separated by " • "
  top_indicators   : array of 3 strings

REASON FORMAT (STRICT):
Use exactly this style, 3 bullets separated by " • ":
"Bullish 15m trend with bullish rejection and higher lows on 1m supports a BUY. • Stop loss set just below entry by 1 ATR plus 0.35 spread buffer, staying above swing low for tight risk. • News feed unavailable; no high-impact events identified, so no news-based adjustment made."

Rules:
1. Higher TF trend MUST agree before BUY/SELL on lower TF.
2. RSI > 70 overbought, < 30 oversold.
3. Volume spike confirms breakout.
4. If TFs conflict → HOLD, confidence low.
5. ATR used for SL distance.
6. "reason" MUST be ONE string with 3 sentences separated by " • " (space-bullet-space).
7. Return ONLY a valid JSON array. NO markdown fences, NO explanation.
"""


# ================= PARSER =================
def _parse_json(text: str) -> list:
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
            # single-key dict
            for v in data.values():
                if isinstance(v, list):
                    return v
        return data if isinstance(data, list) else []
    except Exception as e:
        log.error(f"JSON parse fail: {e}\nRaw: {text[:400]}")
        return []


# ================= GEMINI =================
def _call_gemini(batch: list) -> list:
    if gemini_model is None:
        raise RuntimeError("Gemini not configured")
    prompt = SYSTEM_PROMPT + "\n\nDATA:\n" + json.dumps(batch, separators=(",", ":"))
    resp = gemini_model.generate_content(prompt)
    return _parse_json(resp.text)


# ================= GROQ =================
def _call_groq(batch: list) -> list:
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


# ================= MASTER =================
def analyze_all_pairs(tf_data_per_symbol: dict) -> list:
    """
    tf_data_per_symbol = {"BTCUSDT": {"4h": df, ...}, ...}
    ALL pairs → ONE Gemini call → Groq fallback.
    """
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
                    results.append(_fallback_hold(b["symbol"], "AI unavailable"))
        time.sleep(1.2)

    # Ensure every symbol has result
    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            results.append(_fallback_hold(b["symbol"], "No AI output"))

    return results


def _fallback_hold(symbol: str, reason: str) -> dict:
    return {
        "symbol": symbol, "signal": "HOLD", "confidence": 0,
        "reason": f"{reason}. • No confluence detected. • Waiting for clearer setup.",
        "entry": 0, "stop_loss": 0, "top_indicators": [],
    }