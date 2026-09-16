# subscribers.py
import sqlite3
import logging
from datetime import datetime
from config import SUBSCRIBERS_DB, TELEGRAM_CHAT_IDS

log = logging.getLogger(__name__)


def _conn():
    c = sqlite3.connect(SUBSCRIBERS_DB)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    c.commit()
    return c


def bootstrap_env_ids():
    """Railway env me jo IDs hain unhe DB me daal do (pehli baar)."""
    with _conn() as c:
        for cid in TELEGRAM_CHAT_IDS:
            c.execute(
                "INSERT OR IGNORE INTO subscribers (chat_id, username, added_at) "
                "VALUES (?, ?, ?)",
                (cid, "env", datetime.utcnow().isoformat()),
            )
        c.commit()


def subscribe(chat_id: int, username: str = "") -> bool:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO subscribers (chat_id, username, added_at, active) "
            "VALUES (?, ?, ?, 1)",
            (chat_id, username, datetime.utcnow().isoformat()),
        )
        c.commit()
    log.info(f"✅ Subscribed: {chat_id} ({username})")
    return True


def unsubscribe(chat_id: int) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        c.commit()
    log.info(f"❌ Unsubscribed: {chat_id}")
    return True


def get_all_subscribers() -> list[int]:
    """Sirf active subscribers."""
    with _conn() as c:
        rows = c.execute(
            "SELECT chat_id FROM subscribers WHERE active = 1"
        ).fetchall()
    return [r[0] for r in rows]


def count_subscribers() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]