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

You will receive:
1. READY_PAIRS — new trade setups (pre-filtered by strategy)
2. RECENT_OUTCOMES — what happened to previous signals (TP_HIT/SL_HIT/REVERSAL)

For each READY PAIR, return JSON object with EXACT keys:
  symbol         : string
  signal         : "BUY" | "SELL" | "HOLD"
  confidence     : integer 0-100
  entry          : number (current price from smallest TF close) — NEVER 0
  stop_loss      : number (ATR-based or beyond nearest Fib level)
  take_profit    : number (1:2 minimum risk-reward)
  reason         : string with 3 sentences separated by " • "
  fib_analysis   : string — how Fibonacci influences this trade
  smc_analysis   : string — BOS/FVG confluence note
  top_indicators : array of 3 strings

CRITICAL RULES:
1. entry MUST be > 0. Use current close. NEVER 0.
2. LEARNING from RECENT_OUTCOMES:
   - If same symbol had SL_HIT recently → be extra cautious, lower confidence
   - If same symbol had TP_HIT → that strategy works, similar logic favored
   - If same symbol had REVERSAL → market changed, adjust setup
3. Fibonacci alignment + 3+ confluences → confidence 70-90
4. Weak setup → HOLD with confidence 30-50
5. SL must respect nearest Fibonacci level
6. Return ONLY valid JSON array, no markdown fences, no explanation.
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
def _call_gemini(payload):
    if gemini_model is None:
        raise RuntimeError("Gemini not configured")
    prompt = SYSTEM_PROMPT + "\n\nDATA:\n" + json.dumps(payload, separators=(",", ":"))
    log.info(f"📡 Gemini request: {len(prompt)} chars")
    resp = gemini_model.generate_content(prompt)
    return _parse_json(resp.text)


def _call_groq(payload):
    if groq_client is None:
        raise RuntimeError("Groq not configured")
    resp = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": json.dumps(payload, separators=(",", ":"))},
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


# ==================== RECENT OUTCOMES ====================
def _get_recent_outcomes():
    """
    Pichle signals ka outcome load karo — AI ko learning ke liye bhejna hai.
    """
    try:
        from signal_tracker import check_all_signals
        outcomes = check_all_signals()
        summary = []
        for o in outcomes:
            summary.append({
                "symbol": o["symbol"],
                "prev_signal": o.get("direction", "?"),
                "status": o["status"],           # TP_HIT | SL_HIT | REVERSAL | RUNNING
                "pnl_pct": o.get("pnl_pct", 0),
                "tp_level": o.get("tp_level", 0),
            })
        log.info(f"📊 Recent outcomes for AI: {len(summary)} signals")
        return summary
    except Exception as e:
        log.warning(f"get_recent_outcomes fail: {e}")
        return []


# ==================== MAIN: READY PAIRS ====================
def analyze_ready_pairs(ready_pairs):
    """
    Sirf ready pairs AI ko bhejo + recent outcomes for learning.
    Gemini primary, Groq fallback.
    """
    if not ready_pairs:
        log.info("⚠️ No ready pairs — skipping AI")
        return []

    # Ready pairs ko compact banao
    bundles = []
    for rp in ready_pairs:
        bundles.append({
            "symbol": rp["symbol"],
            "score": rp["score"],
            "direction_hint": rp["direction"],
            "reasons": rp["reasons"],
            "tf_summary": rp["tf_summary"],
        })

    # Recent outcomes (learning ke liye)
    recent_outcomes = _get_recent_outcomes()

    # Combined payload
    payload = {
        "ready_pairs": bundles,
        "recent_outcomes": recent_outcomes,
    }

    total_chars = len(json.dumps(payload, separators=(",", ":")))
    log.info(f"📦 AI payload: {len(bundles)} ready pairs + {len(recent_outcomes)} outcomes")
    log.info(f"📊 Payload size: {total_chars} chars (~{total_chars // 4} tokens)")

    # Chunked send
    chunks = [bundles[i:i+GEMINI_BATCH_SIZE] for i in range(0, len(bundles), GEMINI_BATCH_SIZE)]
    log.info(f"🔪 {len(chunks)} chunks of {GEMINI_BATCH_SIZE}")

    results = []
    for idx, chunk in enumerate(chunks, 1):
        log.info(f"→ Chunk {idx}/{len(chunks)} ({len(chunk)} pairs)")

        # Har chunk me outcomes bhi bhejo (learning)
        chunk_payload = {
            "ready_pairs": chunk,
            "recent_outcomes": recent_outcomes,
        }

        out = None

        # Gemini first
        try:
            out = _call_gemini(chunk_payload)
            if out:
                log.info(f"✅ Gemini OK chunk {idx}")
        except Exception as e:
            log.warning(f"⚠️ Gemini failed chunk {idx}: {str(e)[:200]}")

        # Groq fallback
        if not out:
            try:
                log.info(f"→ Groq fallback chunk {idx}")
                out = _call_groq(chunk_payload)
                if out:
                    log.info(f"✅ Groq OK chunk {idx}")
            except Exception as e:
                log.error(f"❌ Groq failed chunk {idx}: {str(e)[:200]}")

        # Dono fail — HOLD
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

    # Ensure all symbols have results
    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            last = 0
            if b["tf_summary"]:
                tfs = list(b["tf_summary"].keys())
                last = b["tf_summary"][tfs[-1]].get("close", 0)
            results.append(_fallback_hold(b["symbol"], "No AI output", last))

    return results


# ==================== LEGACY ALIAS ====================
def analyze_all_pairs(tf_data_per_symbol):
    """
    Purane code ke liye alias — strategy filter ke saath.
    """
    from strategies import find_ready_pairs
    ready = find_ready_pairs(tf_data_per_symbol, min_score=3)
    if not ready:
        log.info("⚠️ No ready pairs — returning HOLDs")
        return [
            _fallback_hold(sym, "No confluence detected", 0)
            for sym in tf_data_per_symbol.keys()
        ]
    return analyze_ready_pairs(ready)


def build_indicator_bundle(symbol, tf_data):
    """Purane code ke liye compatibility."""
    from strategies import score_pair
    result = score_pair(symbol, tf_data)
    return {
        "symbol": symbol,
        "timeframes": result.get("tf_summary", {}),
    }