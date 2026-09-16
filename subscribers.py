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
            auto_signal INTEGER DEFAULT 1
        )
    """)
    c.commit()
    return c


def bootstrap_env_ids():
    with _conn() as c:
        for cid in TELEGRAM_CHAT_IDS:
            c.execute(
                "INSERT OR IGNORE INTO subscribers (chat_id, username, added_at, auto_signal) "
                "VALUES (?, ?, ?, 1)",
                (cid, "env", datetime.utcnow().isoformat()),
            )
        c.commit()


def subscribe(chat_id: int, username: str = "") -> bool:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO subscribers (chat_id, username, added_at, auto_signal) "
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


def set_auto_signal(chat_id: int, enabled: bool) -> bool:
    with _conn() as c:
        c.execute(
            "UPDATE subscribers SET auto_signal = ? WHERE chat_id = ?",
            (1 if enabled else 0, chat_id),
        )
        c.commit()
    return True


def is_auto_signal_on(chat_id: int) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT auto_signal FROM subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return bool(row[0]) if row else False


def get_signal_subscribers() -> list[int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT chat_id FROM subscribers WHERE auto_signal = 1"
        ).fetchall()
    return [r[0] for r in rows]


def get_all_subscribers() -> list[int]:
    with _conn() as c:
        rows = c.execute("SELECT chat_id FROM subscribers").fetchall()
    return [r[0] for r in rows]


def count_subscribers() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM subscribers").fetchone()[0]