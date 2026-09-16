# main.py
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from config import ANALYSIS_INTERVAL_MINUTES
from data_fetcher import fetch_all_pairs_raw
from ai_analyzer import analyze_all_pairs
from bot import build_application, send_signal, cleanup_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

telegram_app = build_application()


async def run_analysis_async():
    try:
        cleanup_signals(telegram_app.bot)
        log.info("🔍 Fetching 19 pairs data...")
        raw = fetch_all_pairs_raw()
        log.info(f"📊 Data ready for {len(raw)} pairs")

        log.info("🧠 Sending to AI (Gemini batch → Groq fallback)...")
        results = analyze_all_pairs(raw)
        log.info(f"✅ AI returned {len(results)} signals")

        for sig in results:
            await send_signal(telegram_app, sig)
    except Exception:
        log.exception("Analysis cycle crashed")


def scheduled_job():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async())
    finally:
        loop.close()


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_job,
        "interval",
        minutes=ANALYSIS_INTERVAL_MINUTES,
        id="analysis",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow(),
    )
    scheduler.start()
    log.info(f"⏰ Scheduler started — every {ANALYSIS_INTERVAL_MINUTES} min")


def main():
    start_scheduler()
    log.info("🤖 Telegram bot polling...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()