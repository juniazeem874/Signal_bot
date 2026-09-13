import logging

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

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

BRAND = "MJ TRADERS"

CATEGORIES = {
    "crypto": ("💰 Crypto", getattr(config, "CRYPTO_PAIRS", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])),
    "forex": ("💱 Forex", getattr(config, "FOREX_PAIRS", ["EUR/USD", "GBP/USD", "USD/JPY"])),
    "metals": ("🥇 Gold", getattr(config, "METAL_PAIRS", ["XAU/USD", "XAG/USD"])),
}
LABEL_TO_CATEGORY = {label: key for key, (label, _pairs) in CATEGORIES.items()}
ALL_PAIRS_SET = {p for _label, pairs in CATEGORIES.values() for p in pairs}

BACK_LABEL = "⬅️ Back"
STATUS_LABEL = "📊 Status"
AUTO_ON_LABEL = "🟢 Auto ON"
AUTO_OFF_LABEL = "🔴 Auto OFF"

DEFAULT_PAIRS = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"])
SCAN_INTERVAL = getattr(config, "AUTO_SCAN_INTERVAL", 60)

# Duplicate-signal guard: {symbol: "SIGNAL_time"}
LAST_SIGNALS = {}


# ==================== MARKDOWN-SAFE SEND HELPERS ====================
# AI-generated "reasons" text (and key names with underscores) can contain
# characters Telegram's legacy Markdown parser chokes on (stray _ * [ ]),
# which makes send_message/reply_text raise and the handler go silent.
# These helpers retry as plain text instead of failing silently.

def _strip_markdown(text: str) -> str:
    for ch in ("**", "`", "_", "*"):
        text = text.replace(ch, "")
    return text


async def safe_reply(update: Update, text: str, reply_markup=None):
    try:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Markdown reply failed, retrying as plain text: {e}")
        await update.message.reply_text(_strip_markdown(text), reply_markup=reply_markup)


async def safe_send(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Markdown send to {chat_id} failed, retrying as plain text: {e}")
        try:
            await context.bot.send_message(chat_id=chat_id, text=_strip_markdown(text))
        except Exception as e2:
            logger.error(f"Plain-text send to {chat_id} also failed: {e2}")


# ==================== APP-STYLE BOTTOM MENU (persistent keyboard) ====================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    bot_data_auto = _AUTO_STATE.get("enabled", True)
    auto_row = [AUTO_OFF_LABEL if bot_data_auto else AUTO_ON_LABEL]
    return ReplyKeyboardMarkup(
        [
            [CATEGORIES["crypto"][0], CATEGORIES["forex"][0], CATEGORIES["metals"][0]],
            [STATUS_LABEL] + auto_row,
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def pair_menu_keyboard(cat_key: str) -> ReplyKeyboardMarkup:
    _label, pairs = CATEGORIES[cat_key]
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows.append([BACK_LABEL])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


# Tracks auto-trade state for rendering the keyboard label — the real
# source of truth is application.bot_data["auto_trade_enabled"].
_AUTO_STATE = {"enabled": True}


def _category_of(symbol: str) -> str:
    for key, (_label, pairs) in CATEGORIES.items():
        if symbol in pairs:
            return key
    return "crypto"


def _format_signal_message(symbol: str, result: dict, header: str) -> str:
    signal = result.get("signal", "HOLD")
    icon = "🟢" if signal == "BUY" else ("🔴" if signal == "SELL" else "⏸️")
    reasons = result.get("reasons") or []
    reasons_str = "\n".join(f"• {r}" for r in reasons) if reasons else "Strategy conditions met"

    lines = [
        f"{icon} **{BRAND} — {header}** {icon}",
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
    """Shared by /signal and the pair buttons — fetches data, runs the
    strategy, and returns a fully formatted BUY/SELL/HOLD message with reasons."""
    entry_df, trend_df = data_fetcher.get_data(symbol)
    if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
        return f"❌ Market data empty for `{symbol}` — try again in a bit, or check Status."

    result = await strategy.analyze(entry_df, trend_df, symbol)
    return _format_signal_message(symbol, result, "SIGNAL RESULT")


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

            msg = _format_signal_message(symbol, result, "AUTO SIGNAL")
            for chat_id in list(bot_data["active_chat_ids"]):
                await safe_send(context, chat_id, msg)
            signals_sent += 1

        except Exception as pair_err:
            logger.error(f"Couldn't get signal for {symbol}: {pair_err}")

    logger.info(f"Scan cycle done: {pairs_checked}/{len(DEFAULT_PAIRS)} pairs had data, {signals_sent} signal(s) sent.")


# ==================== TELEGRAM HANDLERS ====================

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)
    bot_data["auto_trade_enabled"] = True
    _AUTO_STATE["enabled"] = True

    welcome_msg = (
        f"🤖 **{BRAND}**\n"
        f"Trading Signal Bot\n\n"
        f"Auto-scanning every `{SCAN_INTERVAL}s` across `{len(DEFAULT_PAIRS)}` pairs — "
        f"you'll get BUY/SELL alerts automatically.\n\n"
        "👇 Neeche menu se category chunein, phir pair pe tap karein — "
        "turant BUY/SELL/HOLD analysis reasons ke saath milega."
    )
    await safe_reply(update, welcome_msg, reply_markup=main_menu_keyboard())


def _key_status(name: str, value: str) -> str:
    return "✅ set" if value else "❌ MISSING"


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    enabled = bot_data.get("auto_trade_enabled", False)
    status_str = "🟢 Active" if enabled else "🔴 Disabled"

    groq_status = _key_status("GROQ_API_KEY", getattr(config, "GROQ_API_KEY", ""))
    twelvedata_status = _key_status("TWELVEDATA_API_KEY", getattr(config, "TWELVEDATA_API_KEY", ""))
    finnhub_status = _key_status("FINNHUB_API_KEY", getattr(config, "FINNHUB_API_KEY", ""))
    goldapi_status = _key_status("GOLDAPI_KEY", getattr(config, "GOLDAPI_KEY", ""))

    msg = (
        f"📊 {BRAND} — Bot Status:\n"
        f"Auto-Trade: {status_str}\n"
        f"Scan Interval: {SCAN_INTERVAL}s\n"
        f"Tracked Pairs: {len(DEFAULT_PAIRS)}\n\n"
        f"API Keys:\n"
        f"`GROQ_API_KEY`: {groq_status} (AI analysis)\n"
        f"`TWELVEDATA_API_KEY`: {twelvedata_status}\n"
        f"`FINNHUB_API_KEY`: {finnhub_status}\n"
        f"`GOLDAPI_KEY`: {goldapi_status} (live gold/silver price)\n\n"
        f"If GROQ_API_KEY is MISSING, every scan silently returns HOLD "
        f"and no signal is ever sent."
    )
    await safe_reply(update, msg, reply_markup=main_menu_keyboard())


async def manual_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/signal [PAIR] — instant manual check."""
    symbol = context.args[0].upper() if context.args else "BTCUSDT"
    await safe_reply(update, f"🔍 Fetching analysis for `{symbol}`...")
    try:
        msg = await _run_analysis(symbol)
        await safe_reply(update, msg, reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Manual signal error for {symbol}: {e}")
        await safe_reply(update, f"⚠️ Error: {e}")


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on the persistent bottom menu (ReplyKeyboardMarkup)."""
    text = (update.message.text or "").strip()
    bot_data = context.application.bot_data
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)

    if text == BACK_LABEL:
        await safe_reply(update, f"🤖 {BRAND} — choose a category:", reply_markup=main_menu_keyboard())
        return

    if text == STATUS_LABEL:
        await check_status(update, context)
        return

    if text in (AUTO_ON_LABEL, AUTO_OFF_LABEL):
        turning_on = text == AUTO_ON_LABEL
        bot_data["auto_trade_enabled"] = turning_on
        _AUTO_STATE["enabled"] = turning_on
        msg = "✅ **Auto-Trade Activated!**" if turning_on else "🛑 **Auto-Trade Deactivated.**"
        await safe_reply(update, msg, reply_markup=main_menu_keyboard())
        return

    if text in LABEL_TO_CATEGORY:
        cat_key = LABEL_TO_CATEGORY[text]
        label, _pairs = CATEGORIES[cat_key]
        await safe_reply(update, f"{label} — pick a pair for instant analysis:", reply_markup=pair_menu_keyboard(cat_key))
        return

    symbol = text.upper()
    if symbol in ALL_PAIRS_SET or text in ALL_PAIRS_SET:
        symbol = symbol if symbol in ALL_PAIRS_SET else text
        cat_key = _category_of(symbol)
        await safe_reply(update, f"🔍 Analyzing `{symbol}`...")
        msg = await _run_analysis(symbol)
        await safe_reply(update, msg, reply_markup=pair_menu_keyboard(cat_key))
        return

    # Unrecognized free text — nudge back to the menu instead of staying silent.
    await safe_reply(update, "Neeche menu se koi option chunein 👇", reply_markup=main_menu_keyboard())


# ==================== APP BUILDER ====================

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_enabled"] = getattr(config, "AUTO_SCAN_ENABLED", False)
    _AUTO_STATE["enabled"] = app.bot_data["auto_trade_enabled"]

    app.add_handler(CommandHandler(["start", "help"], send_welcome))
    app.add_handler(CommandHandler("status", check_status))
    app.add_handler(CommandHandler("signal", manual_signal))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    # Runs auto_scan_job every SCAN_INTERVAL seconds in the background.
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=10)

    return app
