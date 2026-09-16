# bot.py
import asyncio
import logging
import time
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, ContextTypes, filters,
)

import config
from config import (
    TELEGRAM_BOT_TOKEN, AUTO_SCAN_INTERVAL, BOT_NAME,
    CRYPTO_PAIRS, FOREX_PAIRS, METAL_PAIRS,
    SIGNAL_EXPIRY_HOURS,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from strategy import compute_signal
from ai_analyzer import analyze_all_pairs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BRAND = "MJ TRADERS"

# ==================== CONSTANTS ====================
BACK_LABEL    = "⬅️ Back"
STATUS_LABEL  = "📊 Status"
AUTO_ON_LABEL  = "🟢 Auto ON"
AUTO_OFF_LABEL = "🔴 Auto OFF"

CATEGORIES = {
    "crypto": ("💰 Crypto", CRYPTO_PAIRS),
    "forex":  ("💱 Forex",  FOREX_PAIRS),
    "metals": ("🥇 Gold",   METAL_PAIRS),
}
LABEL_TO_CATEGORY = {label: key for key, (label, _pairs) in CATEGORIES.items()}
ALL_PAIRS_SET = {p for _label, pairs in CATEGORIES.values() for p in pairs}

DEFAULT_AUTO_ENABLED = getattr(config, "AUTO_SCAN_ENABLED", True)


# ==================== ACTIVE SIGNALS (used by cleanup_signals) ====================
# {symbol: {"signal": ..., "ts": datetime, "msg_ids": {chat_id: msg_id}}}
ACTIVE_SIGNALS: dict[str, dict] = {}


# ==================== AUTO ON/OFF per chat ====================
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
        logger.error(f"Markdown send to {chat_id} failed, retrying as plain text: {e}")
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
def get_main_keyboard(auto_enabled: bool = True) -> ReplyKeyboardMarkup:
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
def _calc_tps(sig: dict) -> tuple:
    """AI ke entry + SL se TP1/TP2/TP3 nikaalo (1:1, 1:2, 1:3)."""
    entry = float(sig.get("entry", 0) or 0)
    sl    = float(sig.get("stop_loss", 0) or 0)
    action = sig.get("signal", "HOLD")
    if entry <= 0 or sl <= 0 or action == "HOLD" or entry == sl:
        return (0, 0, 0, sl)
    risk = abs(entry - sl)
    if action == "BUY":
        return (entry + risk, entry + risk * 2, entry + risk * 3, sl)
    else:
        return (entry - risk, entry - risk * 2, entry - risk * 3, sl)


def _format_reasons(sig: dict) -> str:
    raw = (sig.get("reason") or sig.get("reasons") or "").strip()
    if isinstance(raw, list):
        parts = [str(p).strip() for p in raw if p]
    elif " • " in raw:
        parts = [p.strip() for p in raw.split(" • ") if p.strip()]
    else:
        parts = [p.strip() for p in raw.replace(";", ".").split(".") if p.strip()]
    if not parts:
        return "• No detailed reason available."
    out = []
    for p in parts[:3]:
        if not p.endswith("."):
            p += "."
        out.append(f"• {p}")
    return "\n".join(out)


def format_signal(sig: dict) -> str:
    action = sig.get("signal", "HOLD")
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(action, "⚪")
    entry = float(sig.get("entry", 0) or 0)
    tp1, tp2, tp3, sl = _calc_tps(sig)
    reasons = _format_reasons(sig)

    lines = [
        f"{emoji} *{BRAND} — AUTO SIGNAL* {emoji}",
        "",
        f"Pair: *{sig.get('symbol', '?')}*",
        f"Action: *{action}*",
        f"Price: `{entry}`",
    ]
    if action != "HOLD" and tp1 > 0:
        lines += [
            f"TP1 (1:1): `{round(tp1, 2)}`",
            f"TP2 (1:2): `{round(tp2, 2)}`",
            f"TP3 (1:3): `{round(tp3, 2)}`",
            f"Stop Loss (SL): `{round(sl, 2)}`",
        ]
    lines += [
        f"Confidence: {sig.get('confidence', 0)}%",
        "",
        "*Reasons (why this trade):*",
        reasons,
    ]
    return "\n".join(lines)


# ==================== SEND SIGNAL (used by main.py) ====================
async def send_signal(application, sig: dict, chat_id_override: int = None):
    """
    Ek signal ko sab active chats ko bhejo.
    chat_id_override diya to sirf usi ko.
    """
    bot_data = application.bot_data
    if chat_id_override:
        chat_ids = [chat_id_override]
    else:
        active = list(bot_data.get("active_chat_ids", set()))
        chat_ids = [cid for cid in active if _get_auto_enabled(bot_data, cid)]

    if not chat_ids:
        logger.warning("No active chat subscribers — signal not sent")
        return

    text = format_signal(sig)
    msg_ids = {}
    sent_to = []

    async def _send_one(cid: int):
        try:
            m = await application.bot.send_message(
                chat_id=cid, text=text, parse_mode="Markdown",
            )
            msg_ids[cid] = m.message_id
            sent_to.append(cid)
        except Exception as e:
            logger.warning(f"send fail {sig.get('symbol')}→{cid}: {e}")

    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])

    if msg_ids:
        ACTIVE_SIGNALS[sig["symbol"]] = {
            **sig,
            "ts": datetime.utcnow(),
            "msg_ids": msg_ids,
        }
        logger.info(f"✅ {sig['symbol']} {sig['signal']} → {len(sent_to)} chats")


# ==================== CLEANUP (used by main.py) ====================
def cleanup_signals(bot):
    """6h purane signals delete karo — HOLD bhi rahega."""
    now = datetime.utcnow()
    to_remove = []
    for sym, sig in list(ACTIVE_SIGNALS.items()):
        age = now - sig["ts"]
        if age > timedelta(hours=SIGNAL_EXPIRY_HOURS):
            to_remove.append(sym)

    for sym in to_remove:
        info = ACTIVE_SIGNALS[sym]
        for chat_id, msg_id in info.get("msg_ids", {}).items():
            try:
                bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"delete fail {sym}@{chat_id}: {e}")
        del ACTIVE_SIGNALS[sym]

    if to_remove:
        logger.info(f"🧹 Cleaned {len(to_remove)} signals (> {SIGNAL_EXPIRY_HOURS}h)")


# ==================== MANUAL ANALYSIS (from button click) ====================
async def _run_analysis(symbol: str) -> str:
    try:
        if symbol in CRYPTO_PAIRS:
            tf_data = fetch_crypto_multi_tf(symbol)
        elif symbol in FOREX_PAIRS:
            tf_data = fetch_forex_multi_tf(symbol)
        elif symbol in METAL_PAIRS:
            tf_data = fetch_gold_multi_tf()
        else:
            return f"❌ `{symbol}` not supported"

        if not tf_data:
            return f"❌ No market data for `{symbol}` — try again."

        results = analyze_all_pairs({symbol: tf_data})
        if not results:
            return f"⚠️ AI analysis failed for `{symbol}`."

        return format_signal(results[0])
    except Exception as e:
        logger.error(f"_run_analysis crashed for {symbol}: {e}", exc_info=True)
        return f"⚠️ Analysis failed for `{symbol}`: {e}"


# ==================== STATUS ====================
def _key_status(name: str, value: str) -> str:
    return "✅" if value else "❌ MISSING"


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id  = update.effective_chat.id
    enabled  = _get_auto_enabled(bot_data, chat_id)

    msg = (
        f"📊 *{BRAND} — Status*\n"
        f"Auto: {'🟢 Active' if enabled else '🔴 Disabled'}\n"
        f"Interval: {AUTO_SCAN_INTERVAL // 60} min\n"
        f"Pairs: {len(ALL_PAIRS_SET)}\n"
        f"Signal delete: {SIGNAL_EXPIRY_HOURS}h\n\n"
        f"Gemini: {_key_status('GEMINI', getattr(config, 'GEMINI_API_KEY', ''))}\n"
        f"Groq: {_key_status('GROQ', getattr(config, 'GROQ_API_KEY', ''))}\n"
        f"TwelveData: {_key_status('TWELVEDATA', getattr(config, 'TWELVEDATA_API_KEY', ''))}"
    )
    await safe_reply(update, context, msg,
                     reply_markup=get_main_keyboard(enabled), track_nav=True)


# ==================== WELCOME (first text message) ====================
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id  = update.effective_chat.id
    bot_data.setdefault("active_chat_ids", set()).add(chat_id)
    _set_auto_enabled(bot_data, chat_id, True)

    welcome_msg = (
        f"🤖 *{BRAND}*\n"
        f"Trading Signal Bot\n\n"
        f"Auto-scanning every `{AUTO_SCAN_INTERVAL // 60} min` across `{len(ALL_PAIRS_SET)}` pairs — "
        f"BUY/SELL alerts automatically aayenge.\n\n"
        "👇 Neeche menu se category chunein, phir pair pe tap karein — "
        "turant analysis reasons ke saath milega."
    )
    await safe_reply(update, context, welcome_msg,
                     reply_markup=get_main_keyboard(True), track_nav=True)


# ==================== TEXT HANDLER ====================
async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    await _delete_incoming(update, context)
    bot_data = context.application.bot_data
    chat_id  = update.effective_chat.id
    bot_data.setdefault("active_chat_ids", set()).add(chat_id)

    # ---- /start bhi handle karo (welcome) ----
    if text.startswith("/start") or text.startswith("/help"):
        await send_welcome(update, context)
        return

    # ---- /status command ----
    if text.startswith("/status"):
        await check_status(update, context)
        return

    # ---- BACK ----
    if text == BACK_LABEL:
        await safe_reply(update, context, f"🤖 {BRAND} — choose a category:",
                         reply_markup=get_main_keyboard(_get_auto_enabled(bot_data, chat_id)),
                         track_nav=True)
        return

    # ---- STATUS ----
    if text == STATUS_LABEL:
        await check_status(update, context)
        return

    # ---- AUTO ON/OFF ----
    if text in (AUTO_ON_LABEL, AUTO_OFF_LABEL):
        turning_on = text == AUTO_ON_LABEL
        _set_auto_enabled(bot_data, chat_id, turning_on)
        msg = "✅ *Auto-Trade Activated!*" if turning_on else "🛑 *Auto-Trade Deactivated.*"
        await safe_reply(update, context, msg,
                         reply_markup=get_main_keyboard(turning_on), track_nav=True)
        return

    # ---- CATEGORY ----
    if text in LABEL_TO_CATEGORY:
        cat_key = LABEL_TO_CATEGORY[text]
        label, _pairs = CATEGORIES[cat_key]
        await safe_reply(update, context, f"{label} — pick a pair:",
                         reply_markup=pair_menu_keyboard(cat_key), track_nav=True)
        return

    # ---- PAIR ----
    symbol = text.upper()
    if symbol in ALL_PAIRS_SET or text in ALL_PAIRS_SET:
        symbol = symbol if symbol in ALL_PAIRS_SET else text
        cat_key = _category_of(symbol)
        await safe_reply(update, context, f"🔍 Analyzing `{symbol}`...", track_nav=True)
        msg = await _run_analysis(symbol)
        await safe_reply(update, context, msg, reply_markup=pair_menu_keyboard(cat_key),
                         track_nav=False, delete_prev_nav=True,
                         auto_delete_hours=SIGNAL_EXPIRY_HOURS)
        return

    # ---- UNKNOWN: Welcome dikha do ----
    await send_welcome(update, context)


# ==================== BUILD APP (used by main.py) ====================
def build_app() -> Application:
    """Telegram Application object banao with handlers + keyboard."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN missing!")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Bot state
    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_chats"] = {}
    app.bot_data["nav_msg"] = {}

    # Handler — sab text messages (commands + buttons)
    app.add_handler(MessageHandler(filters.TEXT, handle_menu_text))

    return app