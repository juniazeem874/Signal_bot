# main.py
import os
import asyncio
import logging
from datetime import datetime
from threading import Thread

from flask import Flask
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

# ============ FLASK HEALTH SERVER (Render free tier) ============
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ============ SCHEDULED ANALYSIS ============
telegram_app = build_application()


async def run_analysis_async():
    """Ek cycle: fetch 19 pairs → AI batch → send signals."""
    try:
        cleanup_signals(telegram_app.bot)                     # 1. purge old/HOLD
        log.info("🔍 Fetching 19 pairs data...")
        raw = fetch_all_pairs_raw()                           # 2. 1 gold TwelveData call
        log.info(f"📊 Data ready for {len(raw)} pairs")

        log.info("🧠 Sending to AI (Gemini batch → Groq fallback)...")
        results = analyze_all_pairs(raw)                      # 3. ONE batch call
        log.info(f"✅ AI returned {len(results)} signals")

        for sig in results:
            await send_signal(telegram_app, sig)              # 4. send + track
    except Exception:
        log.exception("Analysis cycle crashed")


def scheduled_job():
    """Sync wrapper — APScheduler background thread se call hota hai."""
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


# ============ ENTRYPOINT ============
def main():
    Thread(target=run_flask, daemon=True).start()
    log.info("🌐 Flask health server running")

    start_scheduler()

    log.info("🤖 Telegram bot polling...")
    telegram_app.run_polling(
        drop_pending_updates=True,
        close_loop=False,
    )


if __name__ == "__main__":
    main()