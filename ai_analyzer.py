8
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

log = logging.getLogger(__name__)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel(GEMINI_MODEL)
else:
    gemini_model = None

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ==================== PROMPT ====================
SYSTEM_PROMPT = f"""You are a professional multi-asset trading analyst for {BOT_NAME} signals channel.

You receive a JSON array of PRE-FILTERED trading setups. Each pair was selected because it shows 
strategy confluence: multi-TF trend, RSI, Volume spike, BOS (Break of Structure), FVG (Fair Value Gap), 
and/or Fibonacci retracement alignment.

Each item includes:
  - symbol, score (0-6), direction_hint ("BUY" | "SELL"), reasons (list)
  - tf_summary: per-TF data with close, rsi, ema20/50/200, macd, atr, trend, bos, fvg, vol_spike, fibonacci

Your job:
1. Confirm or reject the direction hint using the indicators
2. Provide entry, stop_loss, take_profit
3. Explain WHY (3 bullet reasons separated by " • ")
4. Rate confidence 0-100

For EACH asset return JSON object with EXACT keys:
  symbol         : string
  signal         : "BUY" | "SELL" | "HOLD"
  confidence     : integer 0-100
  entry          : number (current price from smallest TF close) — NEVER 0
  stop_loss      : number (use ATR × 1.5 or Fibonacci level)
  take_profit    : number (1:2 minimum risk-reward)
  reason         : string with EXACTLY 3 sentences separated by " • "
  fib_analysis   : string — how Fibonacci influenced this trade
  smc_analysis   : string — BOS/FVG confluence note
  top_indicators : array of 3 strings

CRITICAL RULES:
1. entry MUST always be > 0. Use current close.
2. If setup has 3+ confluences and Fibonacci alignment → confidence 70-90
3. If setup is weak or conflicting → HOLD with confidence 30-50
4. Use Fibonacci:
   - Price IN_GOLDEN_ZONE + trend up → BUY with strong SL below 0.786
   - Price IN_GOLDEN_ZONE + trend down → SELL with strong SL above 0.786
   - Price breaks 0.786 → continuation trade
5. SL must respect nearest Fib level (place SL just beyond it)
6. Return ONLY valid JSON array, no markdown fences.
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
        "smc_analysis": "Unavailable",
        "top_indicators": [],
    }


# ==================== MASTER — AI ONLY FOR READY PAIRS ====================
def analyze_ready_pairs(ready_pairs: list[dict]) -> list[dict]:
    """
    Sirf ready pairs AI ko bhejo — chhota payload.
    
    ready_pairs = [
        {
            "symbol": "BTCUSDT",
            "score": 4,
            "direction": "BUY",
            "reasons": [...],
            "tf_summary": {...}
        },
        ...
    ]
    """
    if not ready_pairs:
        log.info("⚠️ No ready pairs — skipping AI")
        return []

    # Compact format for AI
    bundles = []
    for rp in ready_pairs:
        bundle = {
            "symbol": rp["symbol"],
            "score": rp["score"],
            "direction_hint": rp["direction"],
            "reasons": rp["reasons"],
            "tf_summary": rp["tf_summary"],
        }
        bundles.append(bundle)

    log.info(f"📦 AI payload: {len(bundles)} ready pairs")
    total_chars = len(json.dumps(bundles, separators=(",", ":")))
    log.info(f"📊 Payload size: {total_chars} chars (~{total_chars // 4} tokens)")

    # Chunk
    chunks = [bundles[i:i+GEMINI_BATCH_SIZE] for i in range(0, len(bundles), GEMINI_BATCH_SIZE)]
    log.info(f"🔪 {len(chunks)} chunks of {GEMINI_BATCH_SIZE}")

    results = []
    for idx, chunk in enumerate(chunks, 1):
        log.info(f"→ Chunk {idx}/{len(chunks)} ({len(chunk)} pairs)")

        out = None

        # Try Gemini first
        try:
            out = _call_gemini(chunk)
            if out:
                log.info(f"✅ Gemini OK chunk {idx}")
        except Exception as e:
            log.warning(f"⚠️ Gemini failed chunk {idx}: {str(e)[:200]}")

        # Groq fallback
        if not out:
            try:
                log.info(f"→ Groq fallback chunk {idx}")
                out = _call_groq(chunk)
                if out:
                    log.info(f"✅ Groq OK chunk {idx}")
            except Exception as e:
                log.error(f"❌ Groq failed chunk {idx}: {str(e)[:200]}")

        # Both fail — HOLD
        if not out:
            for b in chunk:
                last_price = 0
                if b["tf_summary"]:
                    tfs = list(b["tf_summary"].keys())
                    last_price = b["tf_summary"][tfs[-1]].get("close", 0)
                results.append(_fallback_hold(b["symbol"], "AI unavailable", last_price))
        else:
            results.extend(out)

        time.sleep(2)  # safety

    # Ensure all symbols have results
    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            last_price = 0
            if b["tf_summary"]:
                tfs = list(b["tf_summary"].keys())
                last_price = b["tf_summary"][tfs[-1]].get("close", 0)
            results.append(_fallback_hold(b["symbol"], "No AI output", last_price))

    return results