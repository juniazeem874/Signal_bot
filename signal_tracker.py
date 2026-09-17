# signal_tracker.py
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from config import DATA_DIR

log = logging.getLogger(__name__)

TRACKER_FILE = Path(DATA_DIR) / "active_signals.json"


def load_tracked_signals() -> list:
    """Saare active tracked signals load karo."""
    try:
        if not TRACKER_FILE.exists():
            return []
        with open(TRACKER_FILE) as f:
            data = json.load(f)
        signals = data.get("signals", [])
        # Purane (6h+) hata do
        cutoff = datetime.utcnow() - timedelta(hours=6)
        signals = [s for s in signals
                   if datetime.fromisoformat(s["created_at"]) > cutoff]
        return signals
    except Exception as e:
        log.error(f"load_tracked_signals fail: {e}")
        return []


def save_tracked_signals(signals: list) -> bool:
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(signals),
            "signals": signals,
        }
        with open(TRACKER_FILE, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return True
    except Exception as e:
        log.error(f"save_tracked_signals fail: {e}")
        return False


def add_signal_to_tracker(sig: dict):
    """
    Naya signal tracker me add karo.
    Sirf BUY/SELL wale.
    """
    if sig.get("signal") not in ("BUY", "SELL"):
        return

    signals = load_tracked_signals()

    # Duplicate check — same symbol ka active signal ho to overwrite karo
    signals = [s for s in signals if s["symbol"] != sig["symbol"]]

    # Naya signal entry
    entry = {
        "symbol": sig["symbol"],
        "signal": sig["signal"],
        "entry": float(sig.get("entry", 0) or 0),
        "stop_loss": float(sig.get("stop_loss", 0) or 0),
        "take_profit": float(sig.get("take_profit", 0) or 0),
        "confidence": sig.get("confidence", 0),
        "reason": sig.get("reason", ""),
        "created_at": datetime.utcnow().isoformat(),
        "status": "ACTIVE",
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "sl_hit": False,
        "reversal_detected": False,
        "telegram_msg_ids": sig.get("telegram_msg_ids", {}),  # ⭐ Telegram msg IDs
    }
    signals.append(entry)
    save_tracked_signals(signals)
    log.info(f"📌 Tracked: {sig['symbol']} {sig['signal']} @ {entry['entry']}")
    return entry


def get_current_price_simple(symbol: str) -> float:
    """Current price fetch karo (data_fetcher se)."""
    try:
        from data_fetcher import get_current_price
        return get_current_price(symbol)
    except Exception as e:
        log.warning(f"get_current_price fail {symbol}: {e}")
        return 0


def evaluate_signal_outcome(sig: dict) -> dict:
    """
    Ek signal ka outcome check karo current price se.
    Returns:
      {
        "symbol": ..., "status": "TP_HIT"|"SL_HIT"|"RUNNING"|"REVERSAL",
        "tp_hit": 1|2|3, "current_price": ..., "pnl_pct": ...
      }
    """
    symbol = sig["symbol"]
    action = sig["signal"]
    entry = float(sig["entry"])
    sl = float(sig["stop_loss"])
    tp = float(sig["take_profit"])

    current = get_current_price_simple(symbol)
    if current <= 0:
        return {"symbol": symbol, "status": "UNKNOWN", "current_price": 0}

    # PnL % calculate karo
    if action == "BUY":
        pnl_pct = ((current - entry) / entry) * 100
        tp_hit = current >= tp
        sl_hit = current <= sl
        # Reversal: agar price entry ke neeche SL se door ja rahi
        reversal = current < entry - abs(entry - sl) * 0.3
    else:  # SELL
        pnl_pct = ((entry - current) / entry) * 100
        tp_hit = current <= tp
        sl_hit = current >= sl
        reversal = current > entry + abs(sl - entry) * 0.3

    # TP1/2/3 thresholds
    risk = abs(entry - sl)
    if action == "BUY":
        tp1 = entry + risk * 1
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3
    else:
        tp1 = entry - risk * 1
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    status = "RUNNING"
    tp_level = 0
    if sl_hit:
        status = "SL_HIT"
    elif tp_hit or (current >= tp3 if action == "BUY" else current <= tp3):
        status = "TP_HIT"
        tp_level = 3
    elif (current >= tp2 if action == "BUY" else current <= tp2):
        status = "TP_HIT"
        tp_level = 2
    elif (current >= tp1 if action == "BUY" else current <= tp1):
        status = "TP_HIT"
        tp_level = 1
    elif reversal:
        status = "REVERSAL"

    return {
        "symbol": symbol,
        "status": status,
        "tp_level": tp_level,
        "current_price": round(current, 6),
        "pnl_pct": round(pnl_pct, 2),
        "direction": action,
        "entry": entry,
    }


def check_all_signals() -> list:
    """Saare tracked signals ka outcome check karo."""
    signals = load_tracked_signals()
    outcomes = []
    for s in signals:
        try:
            outcome = evaluate_signal_outcome(s)
            outcome["original_signal"] = s
            outcomes.append(outcome)
        except Exception as e:
            log.error(f"evaluate fail {s.get('symbol')}: {e}")
    return outcomes


def update_signal_status(symbol: str, new_status: str, note: str = ""):
    """Signal ka status update karo."""
    signals = load_tracked_signals()
    for s in signals:
        if s["symbol"] == symbol:
            s["status"] = new_status
            s["updated_at"] = datetime.utcnow().isoformat()
            if note:
                s["note"] = note
    save_tracked_signals(signals)


def remove_signal(symbol: str):
    """Signal tracker se hata do."""
    signals = load_tracked_signals()
    signals = [s for s in signals if s["symbol"] != symbol]
    save_tracked_signals(signals)