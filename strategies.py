# strategies.py
import logging
from indicators import fibonacci_retracement

log = logging.getLogger(__name__)


# ==================== SINGLE PAIR SCORING ====================
def score_pair(symbol: str, tf_data: dict) -> dict:
    """
    Ek pair ko check karo — kya ye trade-ready hai?
    
    Returns:
      {
        "symbol": "BTCUSDT",
        "score": 4,                    # 0-6
        "direction": "BUY" | "SELL" | None,
        "reasons": ["Fibonacci golden zone", "RSI oversold", ...],
        "tf_summary": {                # compact summary AI ko dene ke liye
          "4h": {"close": ..., "rsi": ..., "trend": ..., "fib": ...},
          "1h": {...},
          ...
        }
      }
    """
    if not tf_data:
        return {"symbol": symbol, "score": 0, "direction": None, "reasons": [], "tf_summary": {}}

    # ============ COLLECT DATA PER TF ============
    summary = {}
    trends = []
    rsi_values = []
    volume_spikes = []
    bos_flags = []
    fvg_flags = []
    fib_zones = []

    for tf, df in tf_data.items():
        if df is None or df.empty:
            continue
        try:
            last = df.iloc[-1]
            close = float(last["close"])
            rsi = float(last.get("rsi") or 50)
            trend = str(last.get("trend", "NA"))
            vol_spike = bool(last.get("vol_spike", False))
            bos = bool(last.get("bos", False))
            fvg = bool(last.get("fvg", False))

            fib = fibonacci_retracement(df, lookback=50)

            summary[tf] = {
                "close": round(close, 6),
                "rsi": round(rsi, 2),
                "trend": trend,
                "ema20": round(float(last.get("ema20") or 0), 6),
                "ema50": round(float(last.get("ema50") or 0), 6),
                "ema200": round(float(last.get("ema200") or 0), 6),
                "atr": round(float(last.get("atr") or 0), 6),
                "vol_spike": vol_spike,
                "bos": bos,
                "fvg": fvg,
                "macd": round(float(last.get("macd") or 0), 6),
                "macd_sig": round(float(last.get("macd_signal") or 0), 6),
            }

            if fib:
                summary[tf]["fib"] = {
                    "zone": fib["current_zone"],
                    "golden_low": fib["golden_zone"]["low"],
                    "golden_high": fib["golden_zone"]["high"],
                    "nearest": fib["nearest_level"],
                    "direction": fib["direction"],
                }
                fib_zones.append(fib["current_zone"])

            trends.append(trend)
            rsi_values.append(rsi)
            if vol_spike:
                volume_spikes.append(tf)
            if bos:
                bos_flags.append(tf)
            if fvg:
                fvg_flags.append(tf)

        except Exception as e:
            log.warning(f"score_pair {symbol} {tf}: {e}")

    if not summary:
        return {"symbol": symbol, "score": 0, "direction": None, "reasons": [], "tf_summary": {}}

    # ============ SCORING LOGIC ============
    score = 0
    reasons = []
    direction_votes = {"BUY": 0, "SELL": 0}

    # --- 1. Trend Alignment (multi-TF) ---
    up_trends = sum(1 for t in trends if t == "up")
    down_trends = sum(1 for t in trends if t == "down")
    if up_trends >= len(trends) - 1 and up_trends >= 2:
        score += 1
        reasons.append("Strong multi-TF uptrend")
        direction_votes["BUY"] += 2
    elif down_trends >= len(trends) - 1 and down_trends >= 2:
        score += 1
        reasons.append("Strong multi-TF downtrend")
        direction_votes["SELL"] += 2

    # --- 2. RSI Condition ---
    min_rsi = min(rsi_values) if rsi_values else 50
    max_rsi = max(rsi_values) if rsi_values else 50
    if min_rsi < 35:
        score += 1
        reasons.append(f"RSI oversold ({min_rsi:.0f})")
        direction_votes["BUY"] += 1
    elif max_rsi > 65:
        score += 1
        reasons.append(f"RSI overbought ({max_rsi:.0f})")
        direction_votes["SELL"] += 1

    # --- 3. Volume Spike ---
    if volume_spikes:
        score += 1
        reasons.append(f"Volume spike on {', '.join(volume_spikes)}")

    # --- 4. BOS (Break of Structure) ---
    if bos_flags:
        score += 1
        reasons.append(f"BOS on {', '.join(bos_flags)}")

    # --- 5. FVG (Fair Value Gap) ---
    if fvg_flags:
        score += 1
        reasons.append(f"FVG on {', '.join(fvg_flags)}")

    # --- 6. Fibonacci Zone ---
    in_golden = sum(1 for z in fib_zones if z == "IN_GOLDEN_ZONE")
    above_382 = sum(1 for z in fib_zones if z == "ABOVE_0.382")
    below_786 = sum(1 for z in fib_zones if z == "BELOW_0.786")

    if in_golden >= 2:
        score += 1
        reasons.append("Price in Fibonacci golden zone (0.5-0.786)")
        # Golden zone in uptrend = BUY opportunity
        if up_trends >= 2:
            direction_votes["BUY"] += 2
        elif down_trends >= 2:
            direction_votes["SELL"] += 2
    elif in_golden >= 1:
        score += 1
        reasons.append("Price in Fibonacci golden zone on 1 TF")
        if up_trends >= 2:
            direction_votes["BUY"] += 1
        elif down_trends >= 2:
            direction_votes["SELL"] += 1

    # --- Final Direction ---
    direction = None
    if direction_votes["BUY"] > direction_votes["SELL"] and direction_votes["BUY"] >= 2:
        direction = "BUY"
    elif direction_votes["SELL"] > direction_votes["BUY"] and direction_votes["SELL"] >= 2:
        direction = "SELL"

    return {
        "symbol": symbol,
        "score": score,
        "direction": direction,
        "reasons": reasons,
        "tf_summary": summary,
    }


# ==================== FILTER ALL PAIRS ====================
def find_ready_pairs(all_pairs_data: dict, min_score: int = 3) -> list[dict]:
    """
    Saare pairs ko score karo, sirf ready wale return karo.
    
    Args:
        all_pairs_data: {symbol: {tf: df}}
        min_score: minimum score to be "ready" (default 3/6)
    
    Returns:
        List of ready pair dicts, sorted by score (highest first)
    """
    scored = []
    for sym, tf_data in all_pairs_data.items():
        try:
            result = score_pair(sym, tf_data)
            scored.append(result)
        except Exception as e:
            log.error(f"score_pair fail {sym}: {e}")

    # Filter: score >= min_score AND direction is BUY/SELL
    ready = [
        s for s in scored
        if s["score"] >= min_score and s["direction"] in ("BUY", "SELL")
    ]

    # Sort by score desc
    ready.sort(key=lambda x: x["score"], reverse=True)

    # Log summary
    log.info(f"🎯 Ready pairs: {len(ready)}/{len(scored)}")
    for s in ready:
        log.info(f"   {s['symbol']}: {s['direction']} (score {s['score']}/6) — {', '.join(s['reasons'])}")

    return ready