from datetime import datetime, timedelta
from config import SIGNAL_EXPIRY_HOURS, REMOVE_HOLD_SIGNALS

# In-memory active signals store
ACTIVE_SIGNALS: dict[str, dict] = {}   # {symbol: {signal, ts, msg_id}}

def save_signal(symbol, signal_data, msg_id):
    ACTIVE_SIGNALS[symbol] = {
        **signal_data,
        "ts": datetime.utcnow(),
        "msg_id": msg_id,
    }

def cleanup_signals(bot):
    """6 ghante purane + HOLD signals delete karo."""
    now = datetime.utcnow()
    to_remove = []
    for sym, sig in ACTIVE_SIGNALS.items():
        age = now - sig["ts"]
        expired = age > timedelta(hours=SIGNAL_EXPIRY_HOURS)
        is_hold = REMOVE_HOLD_SIGNALS and sig.get("signal") == "HOLD"
        if expired or is_hold:
            to_remove.append(sym)
    for sym in to_remove:
        try:
            bot.delete_message(chat_id=CHAT_ID, message_id=ACTIVE_SIGNALS[sym]["msg_id"])
        except Exception as e:
            log.warning(f"delete failed {sym}: {e}")
        del ACTIVE_SIGNALS[sym]
    log.info(f"Cleaned {len(to_remove)} signals")