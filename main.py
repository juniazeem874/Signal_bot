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
from bot import (
    build_app, send_signal, cleanup_signals,
    process_signal_outcomes,
)
from data_store import save_market_data, save_signals

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("main")

telegram_app = build_app()


async def run_analysis_async(only_crypto=False):
    try:
        log.info("📊 Checking previous signal outcomes...")
        try:
            await process_signal_outcomes(telegram_app)
        except Exception as e:
            log.warning(f"outcomes fail: {e}")

        cleanup_signals(telegram_app.bot)
        clear_cache()

        if only_crypto:
            log.info(f"🪙 WEEKEND — crypto only ({len(CRYPTO_PAIRS)})")
        else:
            log.info(f"🔍 Fetching all pairs ({len(ALL_PAIRS)})...")

        raw_all = fetch_all_pairs_raw()
        raw = {s: t for s, t in raw_all.items() if s in CRYPTO_PAIRS} if only_crypto else raw_all
        log.info(f"📊 Fetched {len(raw)} pairs")

        if not raw:
            return

        save_market_data(raw)

        log.info("🎯 Scoring pairs...")
        ready = find_ready_pairs(raw, min_score=3)

        # Loss-prone filter
        try:
            from loss_analyzer import get_loss_patterns
            patterns = get_loss_patterns()
            avoid = set(patterns.get("pairs_to_avoid", []))
            if avoid:
                before = len(ready)
                ready = [r for r in ready if r["symbol"] not in avoid]
                log.info(f"🚫 Filtered {before - len(ready)} loss-prone pairs")
        except Exception as e:
            log.warning(f"loss filter fail: {e}")

        if not ready:
            log.info("😴 No pairs ready")
            save_signals([])
            return

        log.info(f"🧠 Sending {len(ready)} pairs to AI...")
        results = analyze_ready_pairs(ready)
        log.info(f"✅ AI returned {len(results)} signals")

        save_signals(results)

        from signal_tracker import should_recover

        sent = 0
        skipped = 0
        recoveries = 0

        for sig in results:
            if sig.get("signal") == "HOLD":
                skipped += 1
                continue
            if "AI unavailable" in (sig.get("reason") or ""):
                skipped += 1
                continue

            symbol = sig.get("symbol")
            rec = should_recover(symbol)
            if rec.get("should_recover"):
                sig["is_recovery"] = True
                recoveries += 1
                log.info(f"🔄 Recovery: {symbol}")
            else:
                sig["is_recovery"] = False

            await send_signal(telegram_app, sig)
            sent += 1

        log.info(f"📤 Sent {sent} (skipped {skipped}, recovery {recoveries})")

    except Exception:
        log.exception("Cycle crashed")


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

    # ⭐ 60 min — sirf hour 0 pe
    sch.add_job(
        scheduled_job_weekday, "cron",
        day_of_week="mon-fri",
        hour=f"{start_h}-{end_h}", minute="0",
        id="weekday_analysis", max_instances=1, coalesce=True,
    )
    sch.add_job(
        scheduled_job_weekend, "cron",
        day_of_week="sat,sun",
        hour=f"{start_h}-{end_h}", minute="0",
        id="weekend_analysis", max_instances=1, coalesce=True,
    )
    sch.start()
    log.info("⏰ Scheduler started — 60 min interval")
    log.info(f"   Weekdays: {start_h:02d}:00-{end_h:02d}:59 UTC")
    log.info(f"   Weekends: crypto only")


def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()