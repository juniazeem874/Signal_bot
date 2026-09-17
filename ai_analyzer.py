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


# ==================== SYSTEM PROMPT ====================
SYSTEM_PROMPT = f"""You are a professional multi-asset trading analyst for {BOT_NAME} signals channel.

You will receive:
1. READY_PAIRS — new setups (pre-filtered by strategy)
2. RECENT_OUTCOMES — what happened to previous signals
3. LOSS_PATTERNS — aggregated loss statistics:
   - rsi_overbought_buys: BUYs given when RSI was overbought
   - rsi_oversold_sells: SELLs given when RSI was oversold
   - trend_conflicts: signals against multi-TF trend
   - low_volume_trades: signals without volume confirmation
   - high_confidence_fails: 80%+ confidence signals that failed
   - pairs_to_avoid: pairs with 3+ losses in 48h

═══════════════════════════════════════════════════════
CRITICAL RULES — LOSS PREVENTION:
═══════════════════════════════════════════════════════
1. If rsi_overbought_buys > 2 → NEVER BUY when RSI > 65
2. If rsi_oversold_sells > 2 → NEVER SELL when RSI < 35
3. If trend_conflicts > 3 → ALL TFs must agree on direction
4. If low_volume_trades > 2 → Volume spike REQUIRED
5. If high_confidence_fails > 3 → Cap confidence at 75%
6. If pair in pairs_to_avoid → ALWAYS return HOLD

═══════════════════════════════════════════════════════
For EACH ready pair return JSON with EXACT keys:
═══════════════════════════════════════════════════════
  symbol         : string
  signal         : "BUY" | "SELL" | "HOLD"
  confidence     : integer 0-100
  entry          : number (current price) — NEVER 0
  stop_loss      : number (SL < entry for BUY, SL > entry for SELL)
  take_profit    : number (TP > entry for BUY, TP < entry for SELL)
  reason         : string with EXACTLY 3 sentences separated by " • "
  fib_analysis   : string (1-2 lines)
  smc_analysis   : string (1-2 lines)
  top_indicators : array of 3 strings

QUALITY RULES:
- entry MUST be > 0
- stop_loss MUST be different from entry
- take_profit MUST be different from entry
- Fibonacci alignment + 3+ confluences → 70-90 confidence
- Weak setup → HOLD with 30-50 confidence
- Return ONLY valid JSON array, no markdown
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
        "fib_analysis": "Unavailable", "smc_analysis": "Unavailable",
        "top_indicators": [],
    }


# ==================== RECENT OUTCOMES + LOSS PATTERNS ====================
def _get_recent_outcomes():
    """Recent outcomes + loss patterns AI ko bhejo."""
    try:
        from signal_tracker import check_all_signals
        from loss_analyzer import get_loss_patterns

        outcomes = check_all_signals()
        summary = []
        for o in outcomes:
            entry = {
                "symbol": o["symbol"],
                "prev_signal": o.get("direction", "?"),
                "status": o["status"],
                "pnl_pct": o.get("pnl_pct", 0),
                "tp_level": o.get("tp_level", 0),
                "duration_min": o.get("age_min", 0),
            }
            if o["status"] in ("SL_HIT", "REVERSAL"):
                orig = o.get("original_signal", {})
                entry.update({
                    "original_confidence": orig.get("confidence", 0),
                    "original_entry": orig.get("entry", 0),
                    "current_price": o.get("current_price", 0),
                })
            summary.append(entry)

        patterns = get_loss_patterns()

        log.info(f"📊 Recent outcomes: {len(summary)} signals")
        log.info(f"📊 Loss patterns: {patterns}")

        return {
            "recent_outcomes": summary,
            "loss_patterns": patterns,
        }
    except Exception as e:
        log.warning(f"get_recent_outcomes fail: {e}")
        return {"recent_outcomes": [], "loss_patterns": {}}


# ==================== VALIDATE SIGNAL ====================
def _validate_signal(sig):
    """AI response validate karo — SL/TP entry ke barabar na ho."""
    try:
        entry = float(sig.get("entry", 0) or 0)
        sl = float(sig.get("stop_loss", 0) or 0)
        tp = float(sig.get("take_profit", 0) or 0)
        action = sig.get("signal", "HOLD")

        if action == "HOLD" or entry <= 0:
            return sig

        if action == "BUY":
            if sl >= entry:
                sl = entry * 0.99
            if tp <= entry:
                tp = entry * 1.02
        else:
            if sl <= entry:
                sl = entry * 1.01
            if tp >= entry:
                tp = entry * 0.98

        return {**sig, "entry": entry, "stop_loss": sl, "take_profit": tp}
    except Exception as e:
        log.warning(f"_validate_signal fail {sig.get('symbol')}: {e}")
        return sig


# ==================== MAIN: ANALYZE ====================
def analyze_ready_pairs(ready_pairs):
    """Ready pairs AI ko bhejo + outcomes + loss patterns."""
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

    # Recent + loss patterns
    learning_data = _get_recent_outcomes()

    payload = {
        "ready_pairs": bundles,
        "recent_outcomes": learning_data.get("recent_outcomes", []),
        "loss_patterns": learning_data.get("loss_patterns", {}),
    }

    total_chars = len(json.dumps(payload, separators=(",", ":")))
    log.info(f"📦 AI payload: {len(bundles)} pairs + {len(payload['recent_outcomes'])} outcomes")
    log.info(f"📊 Payload: {total_chars} chars (~{total_chars // 4} tokens)")

    chunks = [bundles[i:i+GEMINI_BATCH_SIZE] for i in range(0, len(bundles), GEMINI_BATCH_SIZE)]
    log.info(f"🔪 {len(chunks)} chunks of {GEMINI_BATCH_SIZE}")

    results = []
    for idx, chunk in enumerate(chunks, 1):
        log.info(f"→ Chunk {idx}/{len(chunks)} ({len(chunk)} pairs)")

        chunk_payload = {
            "ready_pairs": chunk,
            "recent_outcomes": payload["recent_outcomes"],
            "loss_patterns": payload["loss_patterns"],
        }

        out = None

        # Gemini primary
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

        # Both fail
        if not out:
            for b in chunk:
                last = 0
                if b["tf_summary"]:
                    tfs = list(b["tf_summary"].keys())
                    last = b["tf_summary"][tfs[-1]].get("close", 0)
                results.append(_fallback_hold(b["symbol"], "AI unavailable", last))
        else:
            for sig in out:
                results.append(_validate_signal(sig))

        time.sleep(2)

    # Ensure all have results
    got = {r.get("symbol") for r in results}
    for b in bundles:
        if b["symbol"] not in got:
            last = 0
            if b["tf_summary"]:
                tfs = list(b["tf_summary"].keys())
                last = b["tf_summary"][tfs[-1]].get("close", 0)
            results.append(_fallback_hold(b["symbol"], "No AI output", last))

    return results


# ==================== LEGACY ====================
def analyze_all_pairs(tf_data_per_symbol):
    from strategies import find_ready_pairs
    ready = find_ready_pairs(tf_data_per_symbol, min_score=3)
    if not ready:
        return [_fallback_hold(sym, "No confluence", 0) for sym in tf_data_per_symbol.keys()]
    return analyze_ready_pairs(ready)


def build_indicator_bundle(symbol, tf_data):
    from strategies import score_pair
    result = score_pair(symbol, tf_data)
    return {"symbol": symbol, "timeframes": result.get("tf_summary", {})}