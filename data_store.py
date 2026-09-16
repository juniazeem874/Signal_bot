# data_store.py
import json
import logging
from datetime import datetime
from pathlib import Path
from config import DATA_DIR, MARKET_JSON, SIGNALS_JSON

log = logging.getLogger(__name__)

DATA_PATH = Path(DATA_DIR)
DATA_PATH.mkdir(exist_ok=True)

MARKET_FILE  = DATA_PATH / MARKET_JSON
SIGNALS_FILE = DATA_PATH / SIGNALS_JSON


def save_market_data(bundles: dict) -> bool:
    """Har cycle me naya data save karo (latest + history)."""
    try:
        now = datetime.utcnow()
        payload = {
            "timestamp": now.isoformat(),
            "count": len(bundles),
            "data": bundles,
        }
        # Latest (AI ke liye)
        with open(MARKET_FILE, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        # History
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        history_file = DATA_PATH / f"market_{ts_str}.json"
        with open(history_file, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        # Cleanup purani (24h se purani)
        _cleanup_old_files("market_*.json", hours=24)
        log.info(f"💾 Saved market: {len(bundles)} pairs → {MARKET_FILE.name}")
        return True
    except Exception as e:
        log.error(f"save_market_data fail: {e}")
        return False


def save_signals(signals: list) -> bool:
    try:
        now = datetime.utcnow()
        payload = {
            "timestamp": now.isoformat(),
            "count": len(signals),
            "signals": signals,
        }
        with open(SIGNALS_FILE, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        ts_str = now.strftime("%Y%m%d_%H%M%S")
        history_file = DATA_PATH / f"signals_{ts_str}.json"
        with open(history_file, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        _cleanup_old_files("signals_*.json", hours=24)
        log.info(f"💾 Saved {len(signals)} signals → {SIGNALS_FILE.name}")
        return True
    except Exception as e:
        log.error(f"save_signals fail: {e}")
        return False


def _cleanup_old_files(pattern, hours=24):
    try:
        cutoff = datetime.utcnow().timestamp() - (hours * 3600)
        for f in DATA_PATH.glob(pattern):
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception as e:
        log.error(f"cleanup fail: {e}")


def load_market_data(max_age_minutes=10):
    try:
        if not MARKET_FILE.exists():
            return None
        with open(MARKET_FILE) as f:
            payload = json.load(f)
        ts = datetime.fromisoformat(payload["timestamp"])
        age = (datetime.utcnow() - ts).total_seconds() / 60
        if age > max_age_minutes:
            return None
        return payload["data"]
    except Exception as e:
        log.error(f"load_market_data fail: {e}")
        return None


def load_signals(max_age_minutes=10):
    try:
        if not SIGNALS_FILE.exists():
            return None
        with open(SIGNALS_FILE) as f:
            payload = json.load(f)
        ts = datetime.fromisoformat(payload["timestamp"])
        age = (datetime.utcnow() - ts).total_seconds() / 60
        if age > max_age_minutes:
            return None
        return payload["signals"]
    except Exception as e:
        log.error(f"load_signals fail: {e}")
        return None