# main.py
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from config import AUTO_SCAN_INTERVAL, ALL_PAIRS, BOT_NAME
from data_fetcher import fetch_all_pairs_raw, clear_cache
from ai_analyzer import analyze_all_pairs, build_indicator_bundle
from bot import build_app, send_signal, cleanup_signals
from data_store import save_market_data, save_signals

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("main")

telegram_app = build_app()


async def run_analysis_async():
    try:
        cleanup_signals(telegram_app.bot)

        # 1. Clear cache — fresh data
        clear_cache()

        # 2. Fetch 19 pairs (FRESH)
        log.info(f"🔍 Fetching {len(ALL_PAIRS)} pairs (fresh)...")
        raw = fetch_all_pairs_raw()
        log.info(f"📊 Fetched data for {len(raw)} pairs")
        if not raw:
            log.error("❌ No data — skipping")
            return

        # 3. Build bundles with Fibonacci
        bundles = {}
        for sym, tf_data in raw.items():
            b = build_indicator_bundle(sym, tf_data)
            if b["timeframes"]:
                bundles[sym] = b
        log.info(f"📦 Bundles built: {len(bundles)} pairs")

        # 4. Save JSON
        save_market_data(bundles)

        # 5. AI analysis
        log.info("🧠 Sending to AI...")
        results = analyze_all_pairs(raw)
        log.info(f"✅ AI returned {len(results)} signals")

        # 6. Save signals
        save_signals(results)

        # 7. Send to Telegram
        sent = 0
        for sig in results:
            if "AI unavailable" in (sig.get("reason") or ""):
                continue
            await send_signal(telegram_app, sig)
            sent += 1
        log.info(f"📤 Sent {sent} signals")

    except Exception:
        log.exception("❌ Analysis cycle crashed")


def scheduled_job():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async())
    finally:
        loop.close()


def start_scheduler():
    mins = AUTO_SCAN_INTERVAL / 60
    sch = BackgroundScheduler(timezone="UTC")
    sch.add_job(
        scheduled_job, "interval", minutes=mins,
        id="mj_analysis", max_instances=1, coalesce=True,
        next_run_time=datetime.utcnow(),
    )
    sch.start()
    log.info(f"⏰ Scheduler started — every {mins:.0f} min")


def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — Telegram bot polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()