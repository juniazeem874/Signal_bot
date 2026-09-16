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

You receive PRE-FILTERED trading setups (each has score 0-6, direction hint, reasons).
Your job: confirm/reject, give entry/SL/TP, explain why, rate confidence.

For EACH asset return JSON with keys:
  symbol, signal ("BUY"|"SELL"|"HOLD"), confidence (0-100),
  entry (current price, NEVER 0), stop_loss, take_profit,
  reason (3 sentences separated by " • "),
  fib_analysis (string), smc_analysis (string), top_indicators (list of 3)

Rules:
1. entry MUST be > 0.
2. Fibonacci alignment + 3+ confluences → confidence 70-90.
3. Weak setup → HOLD, confidence 30-50.
4. SL must respect nearest Fibonacci level.
5. Return ONLY valid JSON array, no markdown.
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


# ==================== MAIN: READY PAIRS ====================
def analyze_ready_pairs(ready_pairs):
    """Sirf ready pairs AI ko bhejo."""
    if not ready_pairs:
        log.info("⚠️ No ready pairs — skipping AI")
        return []

    bundles = []
    for rp in ready_pairs:
        bundles.append({
            "symbol": rp["symbol"],
            "score": rp["score"],
            "direction_hint": rp["direction"],
            "reasons": rp["reasons"],
            "tf_summary": rp["tf_summary"],
        })

    log.info(f"📦 AI payload: {len(bundles)} ready pairs")
    total_chars = len(json.dumps(bundles, separators=(",", ":")))
    log.info(f"📊 Payload size: {total_chars} chars (~{total_chars // 4} tokens)")

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
            log.warning(f"⚠️ Gemini failed chunk {idx}: {str(e)[:200]}")

        if not out:
            try:
                log.info(f"→ Groq fallback chunk {idx}")
                out = _call_groq(chunk)
                if out:
                    log.info(f"✅ Groq OK chunk {idx}")
            except Exception as e:
                log.error(f"❌ Groq failed chunk {idx}: {str(e)[:200]}")

        if not out:
            for b in chunk:
                last = 0
                if b["tf_summary"]:
                    tfs = list(b["tf_summary"].keys())
                    last = b["tf_summary"][tfs[-1]].get("close", 0)
                results.append(_fallback_hold(b["symbol"], "AI unavailable", last))
        else:
            results.extend(out)

        time.sleep(2)

    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            last = 0
            if b["tf_summary"]:
                tfs = list(b["tf_summary"].keys())
                last = b["tf_summary"][tfs[-1]].get("close", 0)
            results.append(_fallback_hold(b["symbol"], "No AI output", last))

    return results


# ==================== LEGACY SUPPORT (purane code ke liye) ====================
def analyze_all_pairs(tf_data_per_symbol):
    """
    Purane main.py/bot.py ke liye alias.
    Internally strategy filter + analyze_ready_pairs use karta hai.
    """
    from strategies import find_ready_pairs
    ready = find_ready_pairs(tf_data_per_symbol, min_score=3)
    if not ready:
        log.info("⚠️ No ready pairs — returning HOLDs for all")
        return [
            _fallback_hold(sym, "No confluence detected", 0)
            for sym in tf_data_per_symbol.keys()
        ]
    return analyze_ready_pairs(ready)


def build_indicator_bundle(symbol, tf_data):
    """Purane code ke liye — strategies.py me already hai."""
    from strategies import score_pair
    result = score_pair(symbol, tf_data)
    return {
        "symbol": symbol,
        "timeframes": result.get("tf_summary", {}),
    }