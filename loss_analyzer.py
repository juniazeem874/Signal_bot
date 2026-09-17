# loss_analyzer.py
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from config import DATA_DIR

log = logging.getLogger(__name__)

ANALYSIS_FILE = Path(DATA_DIR) / "loss_analysis.json"


# ==================== SAVE / LOAD ====================
def load_loss_analyses() -> list:
    try:
        if not ANALYSIS_FILE.exists():
            return []
        with open(ANALYSIS_FILE) as f:
            data = json.load(f)
        analyses = data.get("analyses", [])
        # 48h+ purane hata do
        cutoff = datetime.utcnow() - timedelta(hours=48)
        analyses = [a for a in analyses
                    if datetime.fromisoformat(a["analyzed_at"]) > cutoff]
        return analyses
    except Exception as e:
        log.error(f"load_loss_analyses fail: {e}")
        return []


def save_loss_analyses(analyses: list) -> bool:
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(analyses),
            "analyses": analyses,
        }
        with open(ANALYSIS_FILE, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return True
    except Exception as e:
        log.error(f"save_loss_analyses fail: {e}")
        return False


# ==================== DEEP ANALYSIS ====================
def analyze_loss(sig: dict, outcome: dict) -> dict:
    """
    SL hit wale signal ka detailed analysis karo.
    
    Args:
      sig: original signal (with indicators snapshot)
      outcome: {status, pnl_pct, current_price, ...}
    
    Returns:
      {
        "symbol": ...,
        "wrong_indicators": [...],   # konsa indicator galat tha
        "lesson": "...",              # kya seekha
        "fix": "...",                 # kya theek karna hai
        "recovery_plan": "..."        # recovery ke liye kya karna hai
      }
    """
    symbol = sig.get("symbol")
    action = sig.get("signal")
    entry = float(sig.get("entry", 0) or 0)
    sl = float(sig.get("stop_loss", 0) or 0)
    confidence = sig.get("confidence", 0)
    reason = sig.get("reason", "")

    # Indicators snapshot (from original signal analysis)
    tf_summary = sig.get("tf_summary", {}) or {}

    wrong_indicators = []
    lesson_parts = []
    fix_parts = []

    # ============ CHECK EACH INDICATOR ============
    for tf, data in tf_summary.items():
        if not isinstance(data, dict):
            continue

        # RSI check
        rsi = data.get("rsi", 50)
        if action == "BUY" and rsi > 70:
            wrong_indicators.append(f"RSI {tf}: {rsi:.0f} (overbought, but BUY given)")
            lesson_parts.append(f"{tf} RSI was overbought ({rsi:.0f}) — BUY risky")
            fix_parts.append(f"Require {tf} RSI < 65 for BUY")
        elif action == "SELL" and rsi < 30:
            wrong_indicators.append(f"RSI {tf}: {rsi:.0f} (oversold, but SELL given)")
            lesson_parts.append(f"{tf} RSI was oversold ({rsi:.0f}) — SELL risky")
            fix_parts.append(f"Require {tf} RSI > 35 for SELL")

        # Trend vs direction check
        trend = data.get("trend", "NA")
        if action == "BUY" and trend == "down":
            wrong_indicators.append(f"Trend {tf}: {trend} (against BUY)")
            lesson_parts.append(f"{tf} trend was DOWN but BUY given")
            fix_parts.append(f"Require {tf} trend UP for BUY")
        elif action == "SELL" and trend == "up":
            wrong_indicators.append(f"Trend {tf}: {trend} (against SELL)")
            lesson_parts.append(f"{tf} trend was UP but SELL given")
            fix_parts.append(f"Require {tf} trend DOWN for SELL")

        # Volume check
        vol_spike = data.get("vol_spike", False)
        if not vol_spike:
            lesson_parts.append(f"{tf} had no volume confirmation")

        # BOS check
        bos = data.get("bos", False)
        if not bos:
            lesson_parts.append(f"{tf} had no BOS confirmation")

        # Fibonacci zone check
        fib = data.get("fibonacci", {})
        current_zone = fib.get("current_zone", "")
        if current_zone not in ("IN_GOLDEN_ZONE", "ABOVE_0.382"):
            lesson_parts.append(f"{tf} price not in favorable Fib zone ({current_zone})")

    # ============ CONFIDENCE CHECK ============
    if confidence >= 80:
        lesson_parts.append(f"High confidence ({confidence}%) was overconfident")

    # ============ RECOVERY PLAN ============
    recovery_plan = (
        f"Wait for fresh confluence on {symbol}. "
        f"Require: (1) Multi-TF trend aligned, "
        f"(2) RSI neutral zone (40-60), "
        f"(3) Volume spike confirmation, "
        f"(4) Clear BOS + FVG, "
        f"(5) Price in Fib golden zone."
    )

    # Build analysis result
    result = {
        "symbol": symbol,
        "action": action,
        "entry": entry,
        "sl": sl,
        "confidence": confidence,
        "pnl_pct": outcome.get("pnl_pct", 0),
        "close_status": outcome.get("status"),
        "duration_min": outcome.get("age_min", 0),
        "wrong_indicators": wrong_indicators,
        "lesson": " | ".join(lesson_parts[:5]) or "Market moved unexpectedly",
        "fix": " | ".join(fix_parts[:5]) or "Require stronger multi-TF confluence",
        "recovery_plan": recovery_plan,
        "analyzed_at": datetime.utcnow().isoformat(),
    }

    return result


def save_loss_analysis(analysis: dict):
    """Analysis result save karo."""
    analyses = load_loss_analyses()
    analyses.append(analysis)
    save_loss_analyses(analyses)
    log.info(f"📊 Loss analysis saved: {analysis['symbol']} ({len(analysis['wrong_indicators'])} wrong indicators)")
    return analysis


# ==================== STRATEGY ADAPTATION ====================
def get_loss_patterns() -> dict:
    """
    Recent losses se patterns nikaalo — konse indicators ne baar baar galat signal diya.
    
    Returns:
      {
        "rsi_overbought_buys": 3,
        "trend_conflicts": 5,
        "low_volume_trades": 2,
        "high_confidence_fails": 4,
        "pairs_to_avoid": ["EUR/GBP", "NZD/USD"]
      }
    """
    analyses = load_loss_analyses()
    patterns = {
        "rsi_overbought_buys": 0,
        "rsi_oversold_sells": 0,
        "trend_conflicts": 0,
        "low_volume_trades": 0,
        "high_confidence_fails": 0,
        "pairs_to_avoid": [],
    }

    pair_loss_count = {}

    for a in analyses:
        # RSI issues
        for ind in a.get("wrong_indicators", []):
            if "RSI" in ind and "overbought" in ind:
                patterns["rsi_overbought_buys"] += 1
            if "RSI" in ind and "oversold" in ind:
                patterns["rsi_oversold_sells"] += 1
            if "Trend" in ind:
                patterns["trend_conflicts"] += 1

        # Low volume
        if "volume" in a.get("lesson", "").lower():
            patterns["low_volume_trades"] += 1

        # High confidence fails
        if a.get("confidence", 0) >= 80:
            patterns["high_confidence_fails"] += 1

        # Pair loss count
        sym = a["symbol"]
        pair_loss_count[sym] = pair_loss_count.get(sym, 0) + 1

    # Pairs to avoid (3+ losses in 48h)
    patterns["pairs_to_avoid"] = [
        sym for sym, count in pair_loss_count.items() if count >= 3
    ]

    return patterns