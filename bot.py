import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import data_fetcher
import strategy

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN missing in config.py / environment!")

DEFAULT_PAIRS = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"])
SCAN_INTERVAL = getattr(config, "AUTO_SCAN_INTERVAL", 60)

# Duplicate-signal guard: {symbol: "SIGNAL_time"}
LAST_SIGNALS = {}


def _format_signal_message(symbol: str, result: dict, header: str) -> str:
    signal = result.get("signal", "HOLD")
    icon = "🟢" if signal == "BUY" else "🔴"
    reasons = result.get("reasons") or []
    reasons_str = "\n".join(f"• {r}" for r in reasons) if reasons else "Strategy conditions met"
    return (
        f"{icon} **{header}** {icon}\n\n"
        f"**Pair:** `{symbol}`\n"
        f"**Action:** `{signal}`\n"
        f"**Entry Price:** `{result.get('price', 'N/A')}`\n"
        f"**Take Profit (TP):** `{result.get('take_profit', 'N/A')}`\n"
        f"**Stop Loss (SL):** `{result.get('stop_loss', 'N/A')}`\n"
        f"**Confidence:** `{result.get('confidence', 'N/A')}%`\n"
        f"**Reasons:**\n{reasons_str}"
    )


async def _send_to_all(context: ContextTypes.DEFAULT_TYPE, chat_ids, message_text: str):
    for chat_id in list(chat_ids):
        try:
            await context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every SCAN_INTERVAL seconds via the JobQueue and scans all pairs."""
    bot_data = context.application.bot_data
    if not bot_data.get("auto_trade_enabled") or not bot_data.get("active_chat_ids"):
        return

    logger.info("Scanning markets for entry setups...")

    for symbol in DEFAULT_PAIRS:
        try:
            entry_df, trend_df = data_fetcher.get_data(symbol)
            if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
                logger.warning(f"Market data missing/empty for {symbol}")
                continue

            result = await strategy.analyze(entry_df, trend_df, symbol)
            signal = result.get("signal", "HOLD")
            if signal == "HOLD":
                continue

            current_time_str = str(entry_df['time'].iloc[-1])
            signal_key = f"{symbol}_{signal}_{current_time_str}"
            if LAST_SIGNALS.get(symbol) == signal_key:
                continue
            LAST_SIGNALS[symbol] = signal_key

            msg = _format_signal_message(symbol, result, "AUTOMATED TRADE SIGNAL")
            await _send_to_all(context, bot_data["active_chat_ids"], msg)

        except Exception as pair_err:
            logger.error(f"Couldn't get signal for {symbol}: {pair_err}")


# ==================== TELEGRAM COMMAND HANDLERS ====================

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)
    # Auto-trade turns on as soon as someone starts the bot.
    bot_data["auto_trade_enabled"] = True

    welcome_msg = (
        "🤖 **Trading Signal Bot Active**\n\n"
        f"Auto-scanning every `{SCAN_INTERVAL}s` — you'll get signals automatically.\n\n"
        "Commands:\n"
        "• `/autoon` - Automatic trading signals ON karein\n"
        "• `/autooff` - Automatic trading signals OFF karein\n"
        "• `/signal [PAIR]` - Instant manual signal check karein (e.g. `/signal BTCUSDT`)\n"
        "• `/status` - Bot status dekhein"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")


async def enable_autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    bot_data["auto_trade_enabled"] = True
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)
    await update.message.reply_text(
        "✅ **Auto-Trade Mode Activated!**\nBot ab background mein market scan karke alerts bheje ga.",
        parse_mode="Markdown"
    )


async def disable_autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.application.bot_data["auto_trade_enabled"] = False
    await update.message.reply_text("🛑 **Auto-Trade Mode Deactivated.**", parse_mode="Markdown")


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    enabled = bot_data.get("auto_trade_enabled", False)
    status_str = "🟢 Active" if enabled else "🔴 Disabled"
    await update.message.reply_text(
        f"📊 **Bot Status:**\nAuto-Trade: `{status_str}`\n"
        f"Scan Interval: `{SCAN_INTERVAL}s`\nTracked Pairs: `{len(DEFAULT_PAIRS)}`",
        parse_mode="Markdown"
    )


async def manual_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single pair ka instant signal check karta hai."""
    symbol = context.args[0].upper() if context.args else "BTCUSDT"

    await update.message.reply_text(f"🔍 Fetching analysis for `{symbol}`...", parse_mode="Markdown")

    try:
        entry_df, trend_df = data_fetcher.get_data(symbol)
        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            await update.message.reply_text(f"❌ Market data empty for `{symbol}`", parse_mode="Markdown")
            return

        result = await strategy.analyze(entry_df, trend_df, symbol)
        signal = result.get("signal", "HOLD")

        if signal == "HOLD":
            await update.message.reply_text(f"⏸️ **{symbol}:** No trade setup right now (HOLD).", parse_mode="Markdown")
        else:
            msg = _format_signal_message(symbol, result, "MANUAL SIGNAL RESULT")
            await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Manual signal error for {symbol}: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")


# ==================== APP BUILDER ====================

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_enabled"] = getattr(config, "AUTO_SCAN_ENABLED", False)

    app.add_handler(CommandHandler(["start", "help"], send_welcome))
    app.add_handler(CommandHandler("autoon", enable_autotrade))
    app.add_handler(CommandHandler("autooff", disable_autotrade))
    app.add_handler(CommandHandler("status", check_status))
    app.add_handler(CommandHandler("signal", manual_signal))

    # Runs auto_scan_job every SCAN_INTERVAL seconds in the background.
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=10)

    return app
