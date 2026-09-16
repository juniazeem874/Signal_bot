# main.py
import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from config import AUTO_SCAN_INTERVAL, ALL_PAIRS, BOT_NAME
from data_fetcher import fetch_all_pairs_raw
from ai_analyzer import analyze_all_pairs
from bot import build_app, send_signal, cleanup_signals

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("main")

telegram_app = build_app()


async def run_analysis_async():
    """Ek cycle: cleanup → fetch 19 pairs → AI batch → send signals."""
    try:
        cleanup_signals(telegram_app.bot)

        log.info("🔍 Fetching 19 pairs (crypto + forex + gold)...")
        raw_data = fetch_all_pairs_raw()
        log.info(f"📊 Fetched data for {len(raw_data)} pairs")

        log.info("🧠 Sending all 19 pairs to AI (batch)...")
        results = analyze_all_pairs(raw_data)
        log.info(f"✅ AI returned {len(results)} signals")

        sent = 0
        for sig in results:
            if sig.get("signal") == "HOLD":
                continue   # sirf BUY/SELL bhejo
            await send_signal(telegram_app, sig)
            sent += 1

        log.info(f"📤 Sent {sent} signals to subscribers")

    except Exception:
        log.exception("❌ Analysis cycle crashed")


def scheduled_job():
    """APScheduler sync wrapper — async cycle ko run karta hai."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async())
    finally:
        loop.close()


def start_scheduler():
    interval_minutes = AUTO_SCAN_INTERVAL / 60   # 300s → 5 min
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_job,
        "interval",
        minutes=interval_minutes,        # ⭐ 5 MINUTE
        id="mj_traders_analysis",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow(), # pehla run turant
    )
    scheduler.start()
    log.info(
        f"⏰ Scheduler started — every {interval_minutes:.0f} min "
        f"({AUTO_SCAN_INTERVAL}s)"
    )


def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — Telegram bot polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()