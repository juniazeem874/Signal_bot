import asyncio
import logging
import time

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
SIGNAL_AUTO_DELETE_HOURS = 6  # trade signals older than this get auto-removed from the chat
SIGNAL_COOLDOWN_SECONDS = 6 * 60 * 60  # don't re-fire an auto signal for the same pair within this window

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
# Wall-clock cooldown guard: {symbol: unix_timestamp_last_sent}
LAST_SIGNAL_SENT_AT = {}

# Tracks auto-trade state for rendering the keyboard label — the real
# source of truth is application.bot_data["auto_trade_enabled"].
_AUTO_STATE = {"enabled": True}


# ==================== SEND HELPERS (Markdown-safe, single-screen, auto-delete) ====================
# 1. AI-generated "reasons" text (and key names with underscores) can contain
#    characters Telegram's legacy Markdown parser chokes on — these helpers
#    retry as plain text instead of failing/hanging silently.
# 2. "App style" single screen: navigating (category/back/analysis) deletes
#    the previous menu message so the chat doesn't fill up with old screens.
# 3. Trade signals auto-delete after SIGNAL_AUTO_DELETE_HOURS.

def _strip_markdown(text: str) -> str:
    for ch in ("**", "`", "_", "*"):
        text = text.replace(ch, "")
    return text


async def _delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception as e:
        logger.warning(f"Could not auto-delete message {data.get('message_id')}: {e}")


def _schedule_auto_delete(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, hours: float):
    context.application.job_queue.run_once(
        _delete_message_job,
        when=hours * 3600,
        data={"chat_id": chat_id, "message_id": message_id},
    )


async def _delete_prev_nav(context: ContextTypes.DEFAULT_TYPE, chat_id):
    nav_map = context.application.bot_data.setdefault("nav_msg", {})
    prev_id = nav_map.get(chat_id)
    if prev_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prev_id)
        except Exception:
            pass  # already gone / too old — fine to ignore


async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str,
                      reply_markup=None, track_nav: bool = False, auto_delete_hours: float = None,
                      delete_prev_nav: bool = None):
    chat_id = update.effective_chat.id
    if delete_prev_nav is None:
        delete_prev_nav = track_nav  # old behavior: track_nav did both
    if delete_prev_nav:
        await _delete_prev_nav(context, chat_id)

    try:
        sent = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Markdown reply failed, retrying as plain text: {e}")
        sent = await update.message.reply_text(_strip_markdown(text), reply_markup=reply_markup)

    if track_nav:
        context.application.bot_data.setdefault("nav_msg", {})[chat_id] = sent.message_id
    if auto_delete_hours:
        _schedule_auto_delete(context, chat_id, sent.message_id, auto_delete_hours)
    return sent


async def safe_send(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str, auto_delete_hours: float = None):
    sent = None
    try:
        sent = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Markdown send to {chat_id} failed, retrying as plain text: {e}")
        try:
            sent = await context.bot.send_message(chat_id=chat_id, text=_strip_markdown(text))
        except Exception as e2:
            logger.error(f"Plain-text send to {chat_id} also failed: {e2}")
    if sent and auto_delete_hours:
        _schedule_auto_delete(context, chat_id, sent.message_id, auto_delete_hours)


async def _delete_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the user's own message (a command or a menu-button tap) right
    after it's received, so taps like /start, Crypto, BTCUSDT, Back, Status
    don't stay visible on the right side of the chat. Telegram lets a bot
    delete any message (its own or the other party's) in a private chat
    within 48 hours — if that fails for any reason (older chat, permissions,
    group chat) we just leave the message in place instead of crashing."""
    msg = update.message
    if not msg:
        return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception as e:
        logger.debug(f"Couldn't delete incoming message {msg.message_id}: {e}")


# ==================== APP-STYLE BOTTOM MENU (persistent keyboard) ====================

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    auto_row = [AUTO_OFF_LABEL if _AUTO_STATE.get("enabled", True) else AUTO_ON_LABEL]
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
    strategy, and returns a fully formatted BUY/SELL/HOLD message with reasons.
    Never raises — any failure becomes a user-visible error message instead of
    leaving the chat stuck on 'Analyzing...' forever."""
    try:
        entry_df, trend_df = data_fetcher.get_data(symbol)
        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            return f"❌ Market data empty for `{symbol}` — try again in a bit, or check Status."

        result = await strategy.analyze(entry_df, trend_df, symbol)
        return _format_signal_message(symbol, result, "SIGNAL RESULT")
    except Exception as e:
        logger.error(f"_run_analysis crashed for {symbol}: {e}", exc_info=True)
        return f"⚠️ Analysis failed for `{symbol}`: {e}\nTry again in a moment."


# Rotates which pair leads each scan cycle so one category (crypto) doesn't
# always claim the Groq per-minute token budget before forex/gold get a turn.
_SCAN_ROTATION = {"offset": 0}


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every SCAN_INTERVAL seconds via the JobQueue and scans all pairs."""
    bot_data = context.application.bot_data
    if not bot_data.get("auto_trade_enabled") or not bot_data.get("active_chat_ids"):
        return

    logger.info("Scanning markets for entry setups...")
    signals_sent = 0
    pairs_checked = 0

    # Rotate the pair order each cycle (round-robin) and space the Groq calls
    # out across the scan window — firing all 19 calls in ~15 seconds blows
    # through Groq's 8000 TPM budget almost immediately, so whichever pairs
    # are scanned first (crypto) get analyzed and everything after gets 429'd
    # into a silent HOLD. Spacing them out lets the per-minute budget refill.
    offset = _SCAN_ROTATION["offset"] % len(DEFAULT_PAIRS)
    ordered_pairs = DEFAULT_PAIRS[offset:] + DEFAULT_PAIRS[:offset]
    _SCAN_ROTATION["offset"] = offset + 1
    per_pair_delay = max(0.5, (SCAN_INTERVAL * 0.85) / max(len(ordered_pairs), 1))

    for i, symbol in enumerate(ordered_pairs):
        if i > 0:
            await asyncio.sleep(per_pair_delay)
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

            now_ts = time.time()
            last_sent_ts = LAST_SIGNAL_SENT_AT.get(symbol)
            if last_sent_ts and (now_ts - last_sent_ts) < SIGNAL_COOLDOWN_SECONDS:
                continue  # still inside this pair's 6-hour cooldown

            current_time_str = str(entry_df['time'].iloc[-1])
            signal_key = f"{symbol}_{signal}_{current_time_str}"
            if LAST_SIGNALS.get(symbol) == signal_key:
                continue
            LAST_SIGNALS[symbol] = signal_key
            LAST_SIGNAL_SENT_AT[symbol] = now_ts

            msg = _format_signal_message(symbol, result, "AUTO SIGNAL")
            for chat_id in list(bot_data["active_chat_ids"]):
                await safe_send(context, chat_id, msg, auto_delete_hours=SIGNAL_AUTO_DELETE_HOURS)
            signals_sent += 1

        except Exception as pair_err:
            logger.error(f"Couldn't get signal for {symbol}: {pair_err}")

    logger.info(f"Scan cycle done: {pairs_checked}/{len(DEFAULT_PAIRS)} pairs had data, {signals_sent} signal(s) sent.")


# ==================== TELEGRAM HANDLERS ====================

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _delete_incoming(update, context)
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
    await safe_reply(update, context, welcome_msg, reply_markup=main_menu_keyboard(), track_nav=True)


def _key_status(name: str, value: str) -> str:
    return "✅ set" if value else "❌ MISSING"


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _delete_incoming(update, context)
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
    await safe_reply(update, context, msg, reply_markup=main_menu_keyboard(), track_nav=True)


async def manual_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/signal [PAIR] — instant manual check."""
    await _delete_incoming(update, context)
    symbol = context.args[0].upper() if context.args else "BTCUSDT"
    await safe_reply(update, context, f"🔍 Fetching analysis for `{symbol}`...", track_nav=True)
    msg = await _run_analysis(symbol)
    await safe_reply(update, context, msg, reply_markup=main_menu_keyboard(),
                      track_nav=False, delete_prev_nav=True, auto_delete_hours=SIGNAL_AUTO_DELETE_HOURS)


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on the persistent bottom menu (ReplyKeyboardMarkup)."""
    text = (update.message.text or "").strip()
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    bot_data.setdefault("active_chat_ids", set()).add(update.effective_chat.id)

    if text == BACK_LABEL:
        await safe_reply(update, context, f"🤖 {BRAND} — choose a category:",
                          reply_markup=main_menu_keyboard(), track_nav=True)
        return

    if text == STATUS_LABEL:
        await check_status(update, context)
        return

    if text in (AUTO_ON_LABEL, AUTO_OFF_LABEL):
        turning_on = text == AUTO_ON_LABEL
        bot_data["auto_trade_enabled"] = turning_on
        _AUTO_STATE["enabled"] = turning_on
        msg = "✅ **Auto-Trade Activated!**" if turning_on else "🛑 **Auto-Trade Deactivated.**"
        await safe_reply(update, context, msg, reply_markup=main_menu_keyboard(), track_nav=True)
        return

    if text in LABEL_TO_CATEGORY:
        cat_key = LABEL_TO_CATEGORY[text]
        label, _pairs = CATEGORIES[cat_key]
        await safe_reply(update, context, f"{label} — pick a pair for instant analysis:",
                          reply_markup=pair_menu_keyboard(cat_key), track_nav=True)
        return

    symbol = text.upper()
    if symbol in ALL_PAIRS_SET or text in ALL_PAIRS_SET:
        symbol = symbol if symbol in ALL_PAIRS_SET else text
        cat_key = _category_of(symbol)
        await safe_reply(update, context, f"🔍 Analyzing `{symbol}`...", track_nav=True)
        msg = await _run_analysis(symbol)
        await safe_reply(update, context, msg, reply_markup=pair_menu_keyboard(cat_key),
                          track_nav=False, delete_prev_nav=True, auto_delete_hours=SIGNAL_AUTO_DELETE_HOURS)
        return

    # Unrecognized free text — nudge back to the menu instead of staying silent.
    await safe_reply(update, context, "Neeche menu se koi option chunein 👇",
                      reply_markup=main_menu_keyboard(), track_nav=True)


# ==================== APP BUILDER ====================

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_enabled"] = getattr(config, "AUTO_SCAN_ENABLED", False)
    app.bot_data["nav_msg"] = {}
    _AUTO_STATE["enabled"] = app.bot_data["auto_trade_enabled"]

    app.add_handler(CommandHandler(["start", "help"], send_welcome))
    app.add_handler(CommandHandler("status", check_status))
    app.add_handler(CommandHandler("signal", manual_signal))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    # Runs auto_scan_job every SCAN_INTERVAL seconds in the background.
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=10)

    return app
