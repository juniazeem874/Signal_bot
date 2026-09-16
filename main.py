# main.py
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    AUTO_SCAN_INTERVAL, ALL_PAIRS, BOT_NAME,
    CRYPTO_PAIRS, FOREX_PAIRS, METAL_PAIRS,
    BOT_START_HOUR_UTC, BOT_END_HOUR_UTC, WEEKEND_CRYPTO_ONLY,
)
from data_fetcher import fetch_all_pairs_raw, clear_cache
from strategies import find_ready_pairs
from ai_analyzer import analyze_ready_pairs
from bot import build_app, send_signal, cleanup_signals
from data_store import save_market_data, save_signals

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("main")

telegram_app = build_app()


async def run_analysis_async(only_crypto: bool = False):
    try:
        cleanup_signals(telegram_app.bot)
        clear_cache()

        # 1. Fetch
        if only_crypto:
            log.info(f"🪙 WEEKEND — fetching ONLY crypto ({len(CRYPTO_PAIRS)} pairs)")
        else:
            log.info(f"🔍 Fetching all pairs ({len(ALL_PAIRS)})...")

        raw_all = fetch_all_pairs_raw()
        raw = {s: t for s, t in raw_all.items() if s in CRYPTO_PAIRS} if only_crypto else raw_all
        log.info(f"📊 Fetched data for {len(raw)} pairs")

        if not raw:
            log.error("❌ No data")
            return

        # 2. Save market data (all pairs — for debugging)
        save_market_data(raw)

        # 3. STRATEGY FILTER — kaunse pairs ready hain?
        log.info("🎯 Scoring pairs for trade readiness...")
        ready = find_ready_pairs(raw, min_score=3)

        if not ready:
            log.info("😴 No pairs ready this cycle — skipping AI")
            save_signals([])
            return

        # 4. AI analysis (sirf ready pairs)
        log.info(f"🧠 Sending {len(ready)} ready pairs to AI...")
        results = analyze_ready_pairs(ready)
        log.info(f"✅ AI returned {len(results)} signals")

        # 5. Save signals
        save_signals(results)

        # 6. Send to Telegram
        sent = 0
        for sig in results:
            if "AI unavailable" in (sig.get("reason") or ""):
                continue
            await send_signal(telegram_app, sig)
            sent += 1
        log.info(f"📤 Sent {sent} signals")

    except Exception:
        log.exception("❌ Analysis cycle crashed")


def scheduled_job_weekday():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async(only_crypto=False))
    finally:
        loop.close()


def scheduled_job_weekend():
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async(only_crypto=True))
    finally:
        loop.close()


def start_scheduler():
    sch = BackgroundScheduler(timezone="UTC")
    start_h = BOT_START_HOUR_UTC
    end_h = BOT_END_HOUR_UTC

    sch.add_job(
        scheduled_job_weekday, "cron",
        day_of_week="mon-fri",
        hour=f"{start_h}-{end_h}", minute="*/5",
        id="weekday_analysis", max_instances=1, coalesce=True,
    )
    sch.add_job(
        scheduled_job_weekend, "cron",
        day_of_week="sat,sun",
        hour=f"{start_h}-{end_h}", minute="*/5",
        id="weekend_analysis", max_instances=1, coalesce=True,
    )
    sch.start()
    log.info(f"⏰ Scheduler started — 5 min interval (weekdays all, weekends crypto)")


def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — Telegram bot polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()