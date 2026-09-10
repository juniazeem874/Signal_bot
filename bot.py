import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

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

CATEGORIES = {
    "crypto": ("💰 Crypto", getattr(config, "CRYPTO_PAIRS", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])),
    "forex": ("💱 Forex", getattr(config, "FOREX_PAIRS", ["EUR/USD", "GBP/USD", "USD/JPY"])),
    "metals": ("🥇 Metals", getattr(config, "METAL_PAIRS", ["XAU/USD", "XAG/USD"])),
}

DEFAULT_PAIRS = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"])
SCAN_INTERVAL = getattr(config, "AUTO_SCAN_INTERVAL", 60)

# Duplicate-signal guard: {symbol: "SIGNAL_time"}
LAST_SIGNALS = {}


def _format_signal_message(symbol: str, result: dict, header: str) -> str:
    signal = result.get("signal", "HOLD")
    icon = "🟢" if signal == "BUY" else ("🔴" if signal == "SELL" else "⏸️")
    reasons = result.get("reasons") or []
    reasons_str = "\n".join(f"• {r}" for r in reasons) if reasons else "Strategy conditions met"

    lines = [
        f"{icon} **{header}** {icon}",
        "",
        f"**Pair:** `{symbol}`",
        f"**Action:** `{signal}`",
        f"**Price:** `{result.get('price', 'N/A')}`",
    ]
    if signal in ("BUY", "SELL"):
        lines += [
            f"**Take Profit (TP):** `{result.get('take_profit', 'N/A')}`",
            f"**Stop Loss (SL):** `{result.get('stop_loss', 'N/A')}`",
        ]
    lines += [
        f"**Confidence:** `{result.get('confidence', 'N/A')}%`",
        "**Reasons (why this trade):**",
        reasons_str,
    ]
    return "\n".join(lines)


async def _run_analysis(symbol: str) -> str:
    """Shared by /signal and the pair-picker buttons — fetches data, runs the
    strategy, and returns a fully formatted BUY/SELL/HOLD message with reasons."""
    entry_df, trend_df = data_fetcher.get_data(symbol)
    if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
        return f"❌ Market data empty for `{symbol}` — try again in a bit, or check /status."

    result = await strategy.analyze(entry_df, trend_df, symbol)
    return _format_signal_message(symbol, result, "SIGNAL RESULT")


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
    signals_sent = 0
    pairs_checked = 0

    for symbol in DEFAULT_PAIRS:
        try:
            entry_df, trend_df = data_fetcher.get_data(symbol)
            if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
                logger.warning(f"Market data missing/empty for {symbol}")
                continue

            pairs_checked += 1
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
            signals_sent += 1

        except Exception as pair_err:
            logger.error(f"Couldn't get signal for {symbol}: {pair_err}")

    logger.info(f"Scan cycle done: {pairs_checked}/{len(DEFAULT_PAIRS)} pairs had data, {signals_sent} signal(s) sent.")


# ==================== INLINE MENU (category -> pair -> analysis) ====================

def _category_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"cat:{key}")]
        for key, (label, _pairs) in CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(buttons)


def _pair_keyboard(cat_key: str) -> InlineKeyboardMarkup:
    _label, pairs = CATEGORIES[cat_key]
    # 2 pairs per row so the list stays compact on mobile.
    rows = []
    for i in range(0, len(pairs), 2):
        row = [InlineKeyboardButton(p, callback_data=f"pair:{p}") for p in pairs[i:i + 2]]
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="back:menu")])
    return InlineKeyboardMarkup(rows)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back:menu":
        await query.edit_message_text(
            "🤖 **Trading Signal Bot**\n\nChoose a category:",
            reply_markup=_category_keyboard(),
            parse_mode="Markdown"
        )
        return

    if data.startswith("cat:"):
        cat_key = data.split(":", 1)[1]
        if cat_key not in CATEGORIES:
            return
        label, _pairs = CATEGORIES[cat_key]
        await query.edit_message_text(
            f"{label} — pick a pair for instant analysis:",
            reply_markup=_pair_keyboard(cat_key),
            parse_mode="Markdown"
        )
        return

    if data.startswith("pair:"):
        symbol = data.split(":", 1)[1]
        await query.edit_message_text(f"🔍 Analyzing `{symbol}`...", parse_mode="Markdown")
        msg = await _run_analysis(symbol)
        await query.edit_message_text(
            msg,
            reply_markup=_pair_keyboard(_category_of(symbol)),
            parse_mode="Markdown"
        )


def _category_of(symbol: str) -> str:
    for key, (_label, pairs) in CATEGORIES.items():
        if symbol in pairs:
            return key
    return "crypto"


# ==================== TELEGRAM COMMAND HANDLERS ====================

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)
    # Auto-trade turns on as soon as someone starts the bot.
    bot_data["auto_trade_enabled"] = True

    welcome_msg = (
        "🤖 **Trading Signal Bot Active**\n\n"
        f"Auto-scanning every `{SCAN_INTERVAL}s` across "
        f"`{len(DEFAULT_PAIRS)}` pairs — you'll get BUY/SELL alerts automatically.\n\n"
        "👇 Tap a category, then a pair, for an instant BUY/SELL/HOLD analysis with reasons.\n\n"
        "Commands:\n"
        "• `/autoon` `/autooff` - auto signals on/off\n"
        "• `/signal [PAIR]` - instant manual check (e.g. `/signal BTCUSDT`)\n"
        "• `/status` - bot status"
    )
    await update.message.reply_text(
        welcome_msg, reply_markup=_category_keyboard(), parse_mode="Markdown"
    )


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


def _key_status(name: str, value: str) -> str:
    return "✅ set" if value else "❌ MISSING"


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    enabled = bot_data.get("auto_trade_enabled", False)
    status_str = "🟢 Active" if enabled else "🔴 Disabled"

    gemini_status = _key_status("GEMINI_API_KEY", getattr(config, "GEMINI_API_KEY", ""))
    twelvedata_status = _key_status("TWELVEDATA_API_KEY", getattr(config, "TWELVEDATA_API_KEY", ""))
    finnhub_status = _key_status("FINNHUB_API_KEY", getattr(config, "FINNHUB_API_KEY", ""))

    await update.message.reply_text(
        f"📊 **Bot Status:**\n"
        f"Auto-Trade: `{status_str}`\n"
        f"Scan Interval: `{SCAN_INTERVAL}s`\n"
        f"Tracked Pairs: `{len(DEFAULT_PAIRS)}`\n\n"
        f"**API Keys:**\n"
        f"GEMINI_API_KEY: {gemini_status}\n"
        f"TWELVEDATA_API_KEY: {twelvedata_status}\n"
        f"FINNHUB_API_KEY: {finnhub_status}\n\n"
        f"⚠️ If GEMINI_API_KEY is MISSING, every scan silently returns HOLD "
        f"and no signal is ever sent — this is the #1 cause of \"no auto signals\".",
        parse_mode="Markdown"
    )


async def manual_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single pair ka instant signal check karta hai."""
    symbol = context.args[0].upper() if context.args else "BTCUSDT"
    await update.message.reply_text(f"🔍 Fetching analysis for `{symbol}`...", parse_mode="Markdown")
    try:
        msg = await _run_analysis(symbol)
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
    app.add_handler(CallbackQueryHandler(menu_callback))

    # Runs auto_scan_job every SCAN_INTERVAL seconds in the background.
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=10)

    return app
