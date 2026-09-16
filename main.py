# main.py
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    AUTO_SCAN_INTERVAL, ALL_PAIRS, BOT_NAME,
    CRYPTO_PAIRS, FOREX_PAIRS, METAL_PAIRS,
)
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


# ==================== ANALYSIS RUNNER ====================
async def run_analysis_async(only_crypto: bool = False):
    """
    only_crypto=True  → sirf crypto pairs (weekend)
    only_crypto=False → sab 19 pairs
    """
    try:
        cleanup_signals(telegram_app.bot)
        clear_cache()

        # ==================== PAIRS SELECT ====================
        if only_crypto:
            pairs_to_fetch = CRYPTO_PAIRS
            log.info(f"🪙 Weekend mode — fetching ONLY crypto ({len(pairs_to_fetch)} pairs)")
        else:
            pairs_to_fetch = ALL_PAIRS
            log.info(f"🔍 Fetching all pairs ({len(pairs_to_fetch)})...")

        # ==================== FETCH ====================
        raw_all = fetch_all_pairs_raw()

        # Filter based on mode
        if only_crypto:
            raw = {sym: tf for sym, tf in raw_all.items() if sym in CRYPTO_PAIRS}
        else:
            raw = raw_all

        log.info(f"📊 Fetched data for {len(raw)} pairs")
        if not raw:
            log.error("❌ No data — skipping")
            return

        # ==================== BUILD BUNDLES ====================
        bundles = {}
        for sym, tf_data in raw.items():
            b = build_indicator_bundle(sym, tf_data)
            if b["timeframes"]:
                bundles[sym] = b
        log.info(f"📦 Bundles built: {len(bundles)} pairs")

        # ==================== SAVE JSON ====================
        save_market_data(bundles)

        # ==================== AI ====================
        log.info("🧠 Sending to AI...")
        results = analyze_all_pairs(raw)
        log.info(f"✅ AI returned {len(results)} signals")

        # ==================== SAVE SIGNALS ====================
        save_signals(results)

        # ==================== SEND ====================
        sent = 0
        for sig in results:
            if "AI unavailable" in (sig.get("reason") or ""):
                continue
            await send_signal(telegram_app, sig)
            sent += 1
        log.info(f"📤 Sent {sent} signals")

    except Exception:
        log.exception("❌ Analysis cycle crashed")


# ==================== WEEKDAY JOB ====================
def weekday_job():
    """Mon-Fri, peak hours — all pairs."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async(only_crypto=False))
    finally:
        loop.close()


# ==================== WEEKEND JOB ====================
def weekend_job():
    """Sat-Sun — sirf crypto."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_analysis_async(only_crypto=True))
    finally:
        loop.close()


# ==================== SCHEDULER ====================
def start_scheduler():
    """
    Trial-safe scheduler:
    - Weekdays: 8 AM - 1 AM PKT (3 AM - 8 PM UTC) — all pairs
    - Weekends: sirf crypto
    - Raat 1 AM - 8 AM PKT: bot sleep
    """
    sch = BackgroundScheduler(timezone="UTC")

    # ---- WEEKDAY JOB (Mon-Fri, 03:00-20:59 UTC, every 5 min) ----
    sch.add_job(
        weekday_job,
        "cron",
        day_of_week="mon-fri",
        hour="3-20",
        minute="*/5",
        id="weekday_analysis",
        max_instances=1,
        coalesce=True,
    )

    # ---- WEEKEND JOB (Sat-Sun, crypto only, 03:00-20:59 UTC, every 5 min) ----
    sch.add_job(
        weekend_job,
        "cron",
        day_of_week="sat,sun",
        hour="3-20",
        minute="*/5",
        id="weekend_analysis",
        max_instances=1,
        coalesce=True,
    )

    sch.start()
    log.info("⏰ Scheduler started")
    log.info("   Weekdays: 03:00-20:59 UTC (8 AM - 1:59 AM PKT) — all pairs")
    log.info("   Weekends: 03:00-20:59 UTC — crypto only")
    log.info("   Sleep: 21:00-02:59 UTC (2 AM - 7:59 AM PKT)")


# ==================== MAIN ====================
def main():
    start_scheduler()
    log.info(f"🤖 {BOT_NAME} — Telegram bot polling started...")
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()