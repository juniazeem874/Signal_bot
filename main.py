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


# ==================== ANALYSIS CYCLE ====================
async def run_analysis_async(only_crypto=False):
    """
    Complete cycle:
    0. Purane signals ka outcome check (losses log karo)
    1. Fresh data fetch
    2. Strategy filter
    3. AI analysis (learning from outcomes)
    4. HOLD skip + duplicate skip
    5. Recovery detection + send
    6. Track naye signals
    """
    try:
        # ============ STEP 0: OUTCOMES + LOSS LOGGING ============
        log.info("📊 Checking previous signal outcomes...")
        try:
            await process_signal_outcomes(telegram_app)
        except Exception as e:
            log.warning(f"process_signal_outcomes fail: {e}")

        # ============ STEP 1: CLEANUP + FETCH ============
        cleanup_signals(telegram_app.bot)
        clear_cache()

        if only_crypto:
            log.info(f"🪙 WEEKEND — fetching ONLY crypto ({len(CRYPTO_PAIRS)} pairs)")
        else:
            log.info(f"🔍 Fetching all pairs ({len(ALL_PAIRS)})...")

        raw_all = fetch_all_pairs_raw()
        raw = {s: t for s, t in raw_all.items() if s in CRYPTO_PAIRS} if only_crypto else raw_all
        log.info(f"📊 Fetched data for {len(raw)} pairs")

        if not raw:
            log.error("❌ No data — skipping cycle")
            return

        # ============ STEP 2: SAVE MARKET DATA ============
        save_market_data(raw)

        # ============ STEP 3: STRATEGY FILTER ============
        log.info("🎯 Scoring pairs for trade readiness...")
        ready = find_ready_pairs(raw, min_score=3)

        if not ready:
            log.info("😴 No pairs ready this cycle")
            save_signals([])
            return

        log.info(f"🧠 Sending {len(ready)} ready pairs to AI...")

        # ============ STEP 4: AI ANALYSIS ============
        results = analyze_ready_pairs(ready)
        log.info(f"✅ AI returned {len(results)} signals")

        # ============ STEP 5: SAVE SIGNALS ============
        save_signals(results)

        # ============ STEP 6: SEND (HOLD skip + Recovery detection) ============
        from signal_tracker import should_recover

        sent = 0
        skipped = 0
        recoveries = 0

        for sig in results:
            # HOLD skip
            if sig.get("signal") == "HOLD":
                skipped += 1
                continue
            if "AI unavailable" in (sig.get("reason") or ""):
                skipped += 1
                continue

            # ⭐ Recovery detection
            symbol = sig.get("symbol")
            recovery_check = should_recover(symbol)
            if recovery_check.get("should_recover"):
                sig["is_recovery"] = True
                recoveries += 1
                log.info(f"🔄 Recovery signal: {symbol} — {recovery_check['reason']}")
            else:
                sig["is_recovery"] = False

            await send_signal(telegram_app, sig)
            sent += 1

        log.info(f"📤 Sent {sent} signals (skipped {skipped} HOLDs, {recoveries} recovery)")

    except Exception:
        log.exception("❌ Analysis cycle crashed")


# ==================== JOB WRAPPERS ====================
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


# ==================== SCHEDULER ====================
def start_scheduler():
    sch = BackgroundScheduler(timezone="UTC")
    start_h = BOT_START_HOUR_UTC
    end_h = BOT_END_HOUR_UTC

    sch.add_job(
        scheduled_job_weekday, "cron",
        day_of_week="mon-fri",
        hour=f"{start_h}-{end_h}", minute="*/15",
        id="weekday_analysis", max_instances=1, coalesce=True,
    )
    sch.add_job(
        scheduled_job_weekend, "cron",
        day_of_week="sat,sun",
        hour=f"{start_h}-{end_h}", minute="*/15",
        id="weekend_analysis", max_instances=1, coalesce=True,
    )
    sch.start()
    log.info("⏰ Scheduler started — 15 min interval")
    log.info(f"   Weekdays: {start_h:02d}:00-{end_h:02d}:59 UTC — all pairs")
    log.info(f"   Weekends: {start_h:02d}:00-{end_h:02d}:59 UTC — crypto only")


# ==================== MAIN ====================
def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — Telegram bot polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()