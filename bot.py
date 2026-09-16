# bot.py
import logging
import traceback
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS,
    SIGNAL_EXPIRY_HOURS, REMOVE_HOLD_SIGNALS,
    CRYPTO_PAIRS, FOREX_PAIRS, GOLD_PAIR,
    GEMINI_API_KEY, GROQ_API_KEY, TWELVEDATA_API_KEY,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from strategy import compute_signal
from subscribers import (
    bootstrap_env_ids, subscribe, unsubscribe,
    get_all_subscribers, count_subscribers,
)

log = logging.getLogger(__name__)

# Bootstrap env IDs → DB on import
bootstrap_env_ids()

# ACTIVE_SIGNALS: {symbol: {msg_id_by_chat: {chat_id: msg_id}, signal, ts}}
ACTIVE_SIGNALS: dict[str, dict] = {}


def save_signal(symbol: str, sig: dict, msg_ids: dict, chat_ids: list):
    ACTIVE_SIGNALS[symbol] = {
        **sig,
        "ts": datetime.utcnow(),
        "msg_ids": msg_ids,      # {chat_id: message_id}
        "chat_ids": chat_ids,
    }


def cleanup_signals(bot):
    """6h purane + HOLD delete karo — sab chats se."""
    now = datetime.utcnow()
    to_remove = []
    for sym, sig in list(ACTIVE_SIGNALS.items()):
        age = now - sig["ts"]
        expired = age > timedelta(hours=SIGNAL_EXPIRY_HOURS)
        is_hold = REMOVE_HOLD_SIGNALS and sig.get("signal") == "HOLD"
        if expired or is_hold:
            to_remove.append(sym)

    for sym in to_remove:
        info = ACTIVE_SIGNALS[sym]
        for chat_id, msg_id in info.get("msg_ids", {}).items():
            try:
                bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                log.warning(f"delete fail {sym}@{chat_id}: {e}")
        del ACTIVE_SIGNALS[sym]

    if to_remove:
        log.info(f"🧹 Cleaned {len(to_remove)} signals")


def format_signal(sig: dict) -> str:
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(sig["signal"], "⚪")
    ind = ", ".join(sig.get("top_indicators", [])) or "—"
    return (
        f"{emoji} *{sig['symbol']}* — *{sig['signal']}*\n"
        f"Confidence: {sig.get('confidence', 0)}%\n"
        f"Entry: `{sig.get('entry', 0)}`\n"
        f"SL: `{sig.get('stop_loss', 0)}`  |  TP: `{sig.get('take_profit', 0)}`\n"
        f"Reason: {sig.get('reason', '—')}\n"
        f"Indicators: {ind}"
    )


# ============ MULTI-CHAT SENDER ============
async def send_signal(application, sig: dict, chat_id_override: int = None):
    """
    Ek signal ko SAB subscribers ko bhejo.
    chat_id_override diya to sirf usi ko bhejo.
    """
    chat_ids = [chat_id_override] if chat_id_override else get_all_subscribers()
    if not chat_ids:
        log.error("❌ No subscribers — signal not sent")
        return

    text = format_signal(sig)
    msg_ids = {}
    sent_to = []

    async def _send_one(cid: int):
        try:
            msg = await application.bot.send_message(
                chat_id=cid, text=text, parse_mode="Markdown"
            )
            msg_ids[cid] = msg.message_id
            sent_to.append(cid)
        except Exception as e:
            log.warning(f"send fail {sig['symbol']}→{cid}: {e}")

    # Parallel send — sab chats ko ek saath
    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])

    if msg_ids:
        save_signal(sig["symbol"], sig, msg_ids, sent_to)
        log.info(f"✅ {sig['symbol']} {sig['signal']} → {len(sent_to)} chats")


# ============ HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Crypto", callback_data="menu_crypto")],
        [InlineKeyboardButton("Forex",  callback_data="menu_forex")],
        [InlineKeyboardButton("Gold",   callback_data="menu_gold")],
        [InlineKeyboardButton("🆔 My Chat ID", callback_data="menu_chatid")],
        [InlineKeyboardButton("📊 Status",     callback_data="menu_status")],
        [InlineKeyboardButton("🧪 Test Pipeline", callback_data="menu_test")],
    ]
    await update.message.reply_text(
        f"🤖 *Signal Bot*\n"
        f"Har 5 min auto-analysis — 19 pairs.\n"
        f"Subscribers: *{count_subscribers()}*\n\n"
        f"Commands:\n"
        f"/start — menu\n"
        f"/subscribe — signals receive karo\n"
        f"/unsubscribe — signals band karo\n"
        f"/signal BTCUSDT — manual signal\n"
        f"/chatid — apna chat ID\n"
        f"/status — bot health",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    uname = update.effective_user.username or update.effective_user.first_name or ""
    subscribe(cid, uname)
    await update.message.reply_text(
        f"✅ Subscribed! Chat ID: `{cid}`\n"
        f"Ab aapko har 5 min signals milenge.\n"
        f"Total subscribers: *{count_subscribers()}*",
        parse_mode="Markdown",
    )


async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    unsubscribe(cid)
    await update.message.reply_text(
        f"❌ Unsubscribed. Ab signals nahi aayenge.\n"
        f"Wapas enable karne ke liye /subscribe bhejo.",
    )


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Your chat ID: `{update.effective_chat.id}`\n\n"
        f"Railway me `TELEGRAM_CHAT_IDS` me add karo:\n"
        f"`{update.effective_chat.id}` (comma se multiple)",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        f"📊 *Bot Status*\n\n"
        f"Env chat IDs: `{TELEGRAM_CHAT_IDS}`\n"
        f"DB subscribers: *{count_subscribers()}*\n"
        f"Your chat ID: `{update.effective_chat.id}`\n"
        f"Gemini key: {'✅' if GEMINI_API_KEY else '❌'}\n"
        f"Groq key: {'✅' if GROQ_API_KEY else '❌'}\n"
        f"TwelveData key: {'✅' if TWELVEDATA_API_KEY else '❌'}\n"
        f"Active signals: {len(ACTIVE_SIGNALS)}"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Testing full pipeline...")
    try:
        from data_fetcher import fetch_all_pairs_raw
        from ai_analyzer import analyze_all_pairs

        raw = fetch_all_pairs_raw()
        await update.message.reply_text(f"📊 Fetched {len(raw)} pairs. Calling AI...")
        results = analyze_all_pairs(raw)
        await update.message.reply_text(
            f"✅ AI returned {len(results)} signals. Sending first 3 to ALL subscribers..."
        )
        for sig in results[:3]:
            await send_signal(context.application, sig)
    except Exception:
        await update.message.reply_text(
            f"❌ Error:\n```\n{traceback.format_exc()[:1000]}\n```",
            parse_mode="Markdown",
        )


async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /signal BTCUSDT")
        return
    sym = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching {sym}...")

    if sym in CRYPTO_PAIRS:
        tf_data = fetch_crypto_multi_tf(sym)
    elif sym in FOREX_PAIRS:
        tf_data = fetch_forex_multi_tf(sym)
    elif sym == GOLD_PAIR:
        tf_data = fetch_gold_multi_tf()
    else:
        await update.message.reply_text(f"❌ {sym} not supported.")
        return

    sig = compute_signal(sym, tf_data)
    await update.message.reply_text(format_signal(sig), parse_mode="Markdown")


async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    cid = q.message.chat.id

    if data == "menu_crypto":
        await q.edit_message_text("Crypto pairs:\n" + "\n".join(CRYPTO_PAIRS))
    elif data == "menu_forex":
        await q.edit_message_text("Forex pairs:\n" + "\n".join(FOREX_PAIRS))
    elif data == "menu_gold":
        await q.edit_message_text(f"Gold: {GOLD_PAIR}")
    elif data == "menu_chatid":
        await q.edit_message_text(f"Your chat ID: `{cid}`", parse_mode="Markdown")
    elif data == "menu_status":
        txt = (
            f"📊 *Status*\n"
            f"Subscribers: *{count_subscribers()}*\n"
            f"Your chat ID: `{cid}`\n"
            f"Active signals: {len(ACTIVE_SIGNALS)}"
        )
        await q.edit_message_text(txt, parse_mode="Markdown")
    elif data == "menu_test":
        await q.edit_message_text("⏳ Running test...")
        try:
            from data_fetcher import fetch_all_pairs_raw
            from ai_analyzer import analyze_all_pairs
            raw = fetch_all_pairs_raw()
            results = analyze_all_pairs(raw)
            await q.message.reply_text(
                f"✅ {len(results)} signals. Sending first 3 to ALL subscribers..."
            )
            for sig in results[:3]:
                await send_signal(context.application, sig)
        except Exception:
            await q.message.reply_text(
                f"❌ Error:\n```\n{traceback.format_exc()[:1000]}\n```",
                parse_mode="Markdown",
            )


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("chatid", chatid_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    return app