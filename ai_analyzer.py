import os, json, time, logging
import google.generativeai as genai
from groq import Groq
from config import (
    GEMINI_API_KEY, GROQ_API_KEY, GEMINI_MODEL, GROQ_MODEL,
    GEMINI_BATCH_SIZE
)

log = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(GEMINI_MODEL)
groq_client  = Groq(api_key=GROQ_API_KEY)


# ================== INDICATOR BUNDLE BUILDER ==================
def build_indicator_bundle(symbol: str, tf_data: dict) -> dict:
    """
    tf_data = { "4h": df, "1h": df, "15m": df, ... }
    Har TF ke liye ek compact row banao — taake token kam lage.
    """
    bundle = {"symbol": symbol, "timeframes": {}}
    for tf, df in tf_data.items():
        if df is None or df.empty:
            continue
        last = df.iloc[-1]
        bundle["timeframes"][tf] = {
            "close":      round(float(last["close"]), 5),
            "rsi":        round(float(last.get("rsi", 0)), 2),
            "ema20":      round(float(last.get("ema20", 0)), 5),
            "ema50":      round(float(last.get("ema50", 0)), 5),
            "ema200":     round(float(last.get("ema200", 0)), 5),
            "macd":       round(float(last.get("macd", 0)), 5),
            "macd_sig":   round(float(last.get("macd_signal", 0)), 5),
            "atr":        round(float(last.get("atr", 0)), 5),
            "volume":     round(float(last.get("volume", 0)), 2),
            "vol_avg":    round(float(df["volume"].tail(20).mean()), 2),
            "vol_spike":  bool(last.get("volume", 0) > 1.5 * df["volume"].tail(20).mean()),
            "trend":      str(last.get("trend", "NA")),      # up/down/sideways
            "bos":        bool(last.get("bos", False)),
            "fvg":        bool(last.get("fvg", False)),
        }
    return bundle


# ================== MASTER BATCH PROMPT ==================
SYSTEM_PROMPT = """You are a professional multi-asset trading analyst.
You will receive a JSON array of 19 assets (crypto, forex, gold) with
multi-timeframe indicator data (RSI, EMA20/50/200, MACD, ATR, Volume,
Volume spike, Trend, BOS, FVG).

For EACH symbol return a JSON object with:
- symbol
- signal: "BUY" | "SELL" | "HOLD"
- confidence: 0-100
- reason: <= 25 words
- entry, stop_loss, take_profit (numbers, ATR-based)
- top_indicators: list of 3 most decisive indicators

Rules:
1. Higher TF trend MUST agree before BUY/SELL on lower TF.
2. RSI > 70 overbought, < 30 oversold.
3. Volume spike confirms breakout.
4. If signals conflict across TFs → HOLD.
5. Return ONLY valid JSON array — no markdown fences.
"""


def _call_gemini(batch: list) -> list:
    prompt = SYSTEM_PROMPT + "\n\nDATA:\n" + json.dumps(batch, separators=(",", ":"))
    resp = gemini_model.generate_content(prompt)
    return _parse_json(resp.text)


def _call_groq(batch: list) -> list:
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


def _parse_json(text: str) -> list:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "signals" in data:
            return data["signals"]
        return data if isinstance(data, list) else [data]
    except Exception as e:
        log.error(f"JSON parse fail: {e}\nRaw: {text[:500]}")
        return []


# ================== MAIN ENTRY (BATCHED + FALLBACK) ==================
def analyze_all_pairs(bundles: list[dict]) -> list[dict]:
    """
    bundles = list of indicator bundles (19 pairs).
    Sends EVERYTHING in ONE Gemini call; on failure → Groq fallback.
    """
    results = []
    for i in range(0, len(bundles), GEMINI_BATCH_SIZE):
        batch = bundles[i : i + GEMINI_BATCH_SIZE]
        try:
            log.info(f"Gemini batch {i//GEMINI_BATCH_SIZE + 1} — {len(batch)} pairs")
            results.extend(_call_gemini(batch))
        except Exception as e:
            log.warning(f"Gemini failed → Groq fallback: {e}")
            try:
                results.extend(_call_groq(batch))
            except Exception as e2:
                log.error(f"Groq also failed: {e2}")
                # neutral fallback so bot doesn't crash
                for b in batch:
                    results.append({
                        "symbol": b["symbol"], "signal": "HOLD",
                        "confidence": 0, "reason": "AI unavailable",
                        "entry": 0, "stop_loss": 0, "take_profit": 0,
                        "top_indicators": [],
                    })
        time.sleep(1.2)   # Gemini free-tier safety
    return results