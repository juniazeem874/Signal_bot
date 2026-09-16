# bot.py
import asyncio
import logging
import time

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, ContextTypes, filters

import config
import data_fetcher
import strategy

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN missing in config.py / environment!")

BRAND = "MJ TRADERS"
SIGNAL_AUTO_DELETE_HOURS = 6
SIGNAL_COOLDOWN_SECONDS = 6 * 60 * 60

CATEGORIES = {
    "crypto": ("💰 Crypto", getattr(config, "CRYPTO_PAIRS", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])),
    "forex":  ("💱 Forex",  getattr(config, "FOREX_PAIRS",  ["EUR/USD", "GBP/USD", "USD/JPY"])),
    "metals": ("🥇 Gold",   getattr(config, "METAL_PAIRS",  ["XAU/USD", "XAG/USD"])),
}
LABEL_TO_CATEGORY = {label: key for key, (label, _pairs) in CATEGORIES.items()}
ALL_PAIRS_SET = {p for _label, pairs in CATEGORIES.values() for p in pairs}

BACK_LABEL = "⬅️ Back"
STATUS_LABEL = "📊 Status"
AUTO_ON_LABEL = "🟢 Auto ON"
AUTO_OFF_LABEL = "🔴 Auto OFF"

DEFAULT_PAIRS = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"])
SCAN_INTERVAL = getattr(config, "AUTO_SCAN_INTERVAL", 300)   # ⭐ 5 minute = 300 sec

LAST_SIGNALS = {}
LAST_SIGNAL_SENT_AT = {}
DEFAULT_AUTO_ENABLED = getattr(config, "AUTO_SCAN_ENABLED", True)


def _get_auto_enabled(bot_data: dict, chat_id) -> bool:
    return bot_data.setdefault("auto_trade_chats", {}).get(chat_id, DEFAULT_AUTO_ENABLED)


def _set_auto_enabled(bot_data: dict, chat_id, value: bool):
    bot_data.setdefault("auto_trade_chats", {})[chat_id] = value


# ==================== SEND HELPERS ====================
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
            pass


async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str,
                     reply_markup=None, track_nav: bool = False, auto_delete_hours: float = None,
                     delete_prev_nav: bool = None):
    chat_id = update.effective_chat.id
    if delete_prev_nav is None:
        delete_prev_nav = track_nav
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
        logger.error(f"Markdown send to {chat_id} failed: {e}")
        try:
            sent = await context.bot.send_message(chat_id=chat_id, text=_strip_markdown(text))
        except Exception as e2:
            logger.error(f"Plain-text send also failed: {e2}")
    if sent and auto_delete_hours:
        _schedule_auto_delete(context, chat_id, sent.message_id, auto_delete_hours)


async def _delete_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception as e:
        logger.debug(f"Couldn't delete incoming message: {e}")


# ==================== KEYBOARDS ====================
def main_menu_keyboard(auto_enabled: bool) -> ReplyKeyboardMarkup:
    auto_row = [AUTO_OFF_LABEL if auto_enabled else AUTO_ON_LABEL]
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


# ==================== SIGNAL FORMAT ====================
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
        tps = result.get("take_profits") or {}
        lines += [
            f"**TP1 (1:1):** `{tps.get('tp1', 'N/A')}`",
            f"**TP2 (1:2):** `{tps.get('tp2', 'N/A')}`",
            f"**TP3 (1:3):** `{tps.get('tp3', 'N/A')}`",
            f"**Stop Loss (SL):** `{result.get('stop_loss', 'N/A')}`",
        ]
    lines += [
        f"**Confidence:** `{result.get('confidence', 'N/A')}%`",
        "**Reasons (why this trade):**",
        reasons_str,
    ]
    return "\n".join(lines)


async def _run_analysis(symbol: str) -> str:
    try:
        entry_df, trend_df = data_fetcher.get_data(symbol)
        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            return f"❌ Market data empty for `{symbol}` — try again in a bit, or check Status."

        result = await strategy.analyze(entry_df, trend_df, symbol)
        return _format_signal_message(symbol, result, "SIGNAL RESULT")
    except Exception as e:
        logger.error(f"_run_analysis crashed for {symbol}: {e}", exc_info=True)
        return f"⚠️ Analysis failed for `{symbol}`: {e}\nTry again in a moment."


# ==================== AUTO-SCAN ====================
_SCAN_ROTATION = {"offset": 0}


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    if not bot_data.get("active_chat_ids"):
        return

    logger.info("Scanning markets for entry setups...")
    signals_sent = 0
    pairs_checked = 0

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

            recipients = [
                cid for cid in list(bot_data["active_chat_ids"])
                if _get_auto_enabled(bot_data, cid)
            ]
            if not recipients:
                continue

            now_ts = time.time()
            last_sent_ts = LAST_SIGNAL_SENT_AT.get(symbol)
            if last_sent_ts and (now_ts - last_sent_ts) < SIGNAL_COOLDOWN_SECONDS:
                continue

            current_time_str = str(entry_df["time"].iloc[-1])
            signal_key = f"{symbol}_{signal}_{current_time_str}"
            if LAST_SIGNALS.get(symbol) == signal_key:
                continue
            LAST_SIGNALS[symbol] = signal_key
            LAST_SIGNAL_SENT_AT[symbol] = now_ts

            msg = _format_signal_message(symbol, result, "AUTO SIGNAL")
            for cid in recipients:
                await safe_send(context, cid, msg, auto_delete_hours=SIGNAL_AUTO_DELETE_HOURS)
            signals_sent += 1

        except Exception as pair_err:
            logger.error(f"Couldn't get signal for {symbol}: {pair_err}")

    logger.info(f"Scan cycle done: {pairs_checked}/{len(DEFAULT_PAIRS)} pairs, {signals_sent} signal(s) sent.")


# ==================== HANDLERS (No Commands) ====================
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered on first text message (not /start). Ye Telegram pe /start ka default handler nahi hai."""
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id = update.effective_chat.id
    bot_data.setdefault("active_chat_ids", set()).add(chat_id)
    _set_auto_enabled(bot_data, chat_id, True)

    welcome_msg = (
        f"🤖 **{BRAND}**\n"
        f"Trading Signal Bot\n\n"
        f"Auto-scanning every `{SCAN_INTERVAL // 60} min` across `{len(DEFAULT_PAIRS)}` pairs — "
        f"you'll get BUY/SELL alerts automatically.\n\n"
        "👇 Neeche menu se category chunein, phir pair pe tap karein — "
        "turant BUY/SELL/HOLD analysis reasons ke saath milega."
    )
    await safe_reply(update, context, welcome_msg,
                     reply_markup=main_menu_keyboard(True), track_nav=True)


def _key_status(name: str, value: str) -> str:
    return "✅ set" if value else "❌ MISSING"


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id = update.effective_chat.id
    enabled = _get_auto_enabled(bot_data, chat_id)
    status_str = "🟢 Active" if enabled else "🔴 Disabled"

    groq_status = _key_status("GROQ_API_KEY", getattr(config, "GROQ_API_KEY", ""))
    gemini_status = _key_status("GEMINI_API_KEY", getattr(config, "GEMINI_API_KEY", ""))
    twelvedata_status = _key_status("TWELVEDATA_API_KEY", getattr(config, "TWELVEDATA_API_KEY", ""))

    msg = (
        f"📊 {BRAND} — Bot Status:\n"
        f"Auto-Trade (this chat): {status_str}\n"
        f"Scan Interval: {SCAN_INTERVAL}s ({SCAN_INTERVAL // 60} min)\n"
        f"Tracked Pairs: {len(DEFAULT_PAIRS)}\n"
        f"Signal Auto-Delete: {SIGNAL_AUTO_DELETE_HOURS}h\n\n"
        f"API Keys:\n"
        f"`GROQ_API_KEY`: {groq_status}\n"
        f"`GEMINI_API_KEY`: {gemini_status}\n"
        f"`TWELVEDATA_API_KEY`: {twelvedata_status}\n\n"
        f"If AI keys are MISSING, every scan silently returns HOLD."
    )
    await safe_reply(update, context, msg,
                     reply_markup=main_menu_keyboard(enabled), track_nav=True)


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id = update.effective_chat.id
    bot_data.setdefault("active_chat_ids", set()).add(chat_id)

    # ===== BACK =====
    if text == BACK_LABEL:
        await safe_reply(update, context, f"🤖 {BRAND} — choose a category:",
                         reply_markup=main_menu_keyboard(_get_auto_enabled(bot_data, chat_id)),
                         track_nav=True)
        return

    # ===== STATUS =====
    if text == STATUS_LABEL:
        await check_status(update, context)
        return

    # ===== AUTO ON/OFF =====
    if text in (AUTO_ON_LABEL, AUTO_OFF_LABEL):
        turning_on = text == AUTO_ON_LABEL
        _set_auto_enabled(bot_data, chat_id, turning_on)
        msg = "✅ **Auto-Trade Activated!**" if turning_on else "🛑 **Auto-Trade Deactivated.**"
        await safe_reply(update, context, msg,
                         reply_markup=main_menu_keyboard(turning_on), track_nav=True)
        return

    # ===== CATEGORY CLICK =====
    if text in LABEL_TO_CATEGORY:
        cat_key = LABEL_TO_CATEGORY[text]
        label, _pairs = CATEGORIES[cat_key]
        await safe_reply(update, context, f"{label} — pick a pair for instant analysis:",
                         reply_markup=pair_menu_keyboard(cat_key), track_nav=True)
        return

    # ===== PAIR CLICK =====
    symbol = text.upper()
    if symbol in ALL_PAIRS_SET or text in ALL_PAIRS_SET:
        symbol = symbol if symbol in ALL_PAIRS_SET else text
        cat_key = _category_of(symbol)
        await safe_reply(update, context, f"🔍 Analyzing `{symbol}`...", track_nav=True)
        msg = await _run_analysis(symbol)
        await safe_reply(update, context, msg, reply_markup=pair_menu_keyboard(cat_key),
                         track_nav=False, delete_prev_nav=True,
                         auto_delete_hours=SIGNAL_AUTO_DELETE_HOURS)
        return

    # ===== UNKNOWN TEXT → Welcome (pehla message) =====
    await safe_reply(update, context,
                     "Neeche menu se koi option chunein 👇",
                     reply_markup=main_menu_keyboard(_get_auto_enabled(bot_data, chat_id)),
                     track_nav=True)


# ==================== APP BUILDER ====================
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_chats"] = {}
    app.bot_data["nav_msg"] = {}

    # ⚠️ Sirf ek handler — sab kuch text messages se handle hoga
    app.add_handler(MessageHandler(filters.TEXT, handle_menu_text))

    # Auto-scan every SCAN_INTERVAL seconds
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL, first=10)

    return app