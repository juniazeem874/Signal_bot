# signal_tracker.py
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from config import DATA_DIR

log = logging.getLogger(__name__)

TRACKER_FILE = Path(DATA_DIR) / "active_signals.json"
RECOVERY_FILE = Path(DATA_DIR) / "recovery_history.json"


# ==================== LOAD / SAVE ====================
def load_tracked_signals() -> list:
    """Saare active tracked signals load karo."""
    try:
        if not TRACKER_FILE.exists():
            return []
        with open(TRACKER_FILE) as f:
            data = json.load(f)
        signals = data.get("signals", [])
        # 6h+ purane hata do
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


# ==================== RECOVERY HISTORY ====================
def load_recovery_history() -> list:
    """Recent losses ka record — recovery planning ke liye."""
    try:
        if not RECOVERY_FILE.exists():
            return []
        with open(RECOVERY_FILE) as f:
            data = json.load(f)
        losses = data.get("losses", [])
        # 24h+ purane hata do
        cutoff = datetime.utcnow() - timedelta(hours=24)
        losses = [l for l in losses
                  if datetime.fromisoformat(l["closed_at"]) > cutoff]
        return losses
    except Exception as e:
        log.error(f"load_recovery_history fail: {e}")
        return []


def save_recovery_history(losses: list) -> bool:
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(losses),
            "losses": losses,
        }
        with open(RECOVERY_FILE, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        return True
    except Exception as e:
        log.error(f"save_recovery_history fail: {e}")
        return False


def log_loss(symbol: str, sig: dict, outcome: dict):
    """
    Ek loss record karo — recovery planning ke liye.
    """
    losses = load_recovery_history()
    entry = {
        "symbol": symbol,
        "action": sig.get("signal"),
        "entry": sig.get("entry"),
        "stop_loss": sig.get("stop_loss"),
        "take_profit": sig.get("take_profit"),
        "confidence": sig.get("confidence", 0),
        "reason": sig.get("reason", ""),
        "fib_analysis": sig.get("fib_analysis", ""),
        "smc_analysis": sig.get("smc_analysis", ""),
        "closed_at": datetime.utcnow().isoformat(),
        "close_price": outcome.get("current_price", 0),
        "close_status": outcome.get("status"),
        "pnl_pct": outcome.get("pnl_pct", 0),
        "duration_min": outcome.get("age_min", 0),
    }
    losses.append(entry)
    save_recovery_history(losses)
    log.info(f"📝 Loss logged: {symbol} {sig.get('signal')} ({outcome.get('pnl_pct')}%)")
    return entry


def get_failed_pairs() -> list:
    """Kaunse pairs recently fail hue — recovery ke liye."""
    losses = load_recovery_history()
    failed = []
    for l in losses:
        if l.get("pnl_pct", 0) < 0:
            failed.append({
                "symbol": l["symbol"],
                "action": l["action"],
                "closed_at": l["closed_at"],
                "pnl_pct": l["pnl_pct"],
                "close_status": l.get("close_status"),
            })
    return failed


def should_recover(symbol: str) -> dict:
    """
    Check karo — is pair pe recovery trade lena chahiye?
    Returns:
      {
        "should_recover": True/False,
        "reason": "...",
        "prev_loss": {...}  # last loss info
      }
    """
    losses = load_recovery_history()
    pair_losses = [l for l in losses if l["symbol"] == symbol]

    if not pair_losses:
        return {"should_recover": False, "reason": "No previous losses"}

    # Sabse recent loss
    latest = max(pair_losses, key=lambda x: x["closed_at"])
    loss_time = datetime.fromisoformat(latest["closed_at"])
    age_min = (datetime.utcnow() - loss_time).total_seconds() / 60

    # Rules:
    # 1. Loss 30+ min pehle hua (fresh setup ke liye)
    # 2. Pichla loss -0.5% se kam (chhota loss, recoverable)
    # 3. Yahi pair 3+ baar fail nahi hua recently

    if age_min < 30:
        return {
            "should_recover": False,
            "reason": f"Loss too recent ({age_min:.0f} min ago)",
            "prev_loss": latest,
        }

    total_losses = len(pair_losses)
    if total_losses >= 3:
        return {
            "should_recover": False,
            "reason": f"Pair failed {total_losses} times — avoid",
            "prev_loss": latest,
        }

    return {
        "should_recover": True,
        "reason": f"Recovery opportunity ({total_losses} loss{'es' if total_losses>1 else ''} earlier)",
        "prev_loss": latest,
    }


# ==================== SIGNAL TRACKING ====================
def add_signal_to_tracker(sig: dict):
    """Naya signal tracker me add karo. Sirf BUY/SELL."""
    if sig.get("signal") not in ("BUY", "SELL"):
        return

    signals = load_tracked_signals()
    signals = [s for s in signals if s["symbol"] != sig["symbol"]]

    entry = {
        "symbol": sig["symbol"],
        "signal": sig["signal"],
        "entry": float(sig.get("entry", 0) or 0),
        "stop_loss": float(sig.get("stop_loss", 0) or 0),
        "take_profit": float(sig.get("take_profit", 0) or 0),
        "confidence": sig.get("confidence", 0),
        "reason": sig.get("reason", ""),
        "fib_analysis": sig.get("fib_analysis", ""),
        "smc_analysis": sig.get("smc_analysis", ""),
        "created_at": datetime.utcnow().isoformat(),
        "status": "ACTIVE",
        "is_recovery": sig.get("is_recovery", False),
        "telegram_msg_ids": sig.get("telegram_msg_ids", {}),
    }
    signals.append(entry)
    save_tracked_signals(signals)
    log.info(f"📌 Tracked: {sig['symbol']} {sig['signal']} @ {entry['entry']}")
    return entry


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


# ==================== OUTCOME EVALUATION ====================
def get_current_price_simple(symbol: str) -> float:
    try:
        from data_fetcher import get_current_price
        return get_current_price(symbol)
    except Exception as e:
        log.warning(f"get_current_price fail {symbol}: {e}")
        return 0


def evaluate_signal_outcome(sig: dict) -> dict:
    """
    Ek signal ka outcome check karo current price se.
    Returns detailed analysis.
    """
    symbol = sig["symbol"]
    action = sig["signal"]
    entry = float(sig["entry"])
    sl = float(sig["stop_loss"])
    tp = float(sig["take_profit"])

    current = get_current_price_simple(symbol)
    if current <= 0:
        return {"symbol": symbol, "status": "UNKNOWN", "current_price": 0}

    # PnL %
    if action == "BUY":
        pnl_pct = ((current - entry) / entry) * 100
        tp_hit = current >= tp
        sl_hit = current <= sl
        reversal = current < entry - abs(entry - sl) * 0.3
    else:
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

    # Duration
    created = datetime.fromisoformat(sig["created_at"])
    age_min = (datetime.utcnow() - created).total_seconds() / 60

    return {
        "symbol": symbol,
        "status": status,
        "tp_level": tp_level,
        "current_price": round(current, 6),
        "pnl_pct": round(pnl_pct, 2),
        "direction": action,
        "entry": entry,
        "age_min": round(age_min, 1),
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