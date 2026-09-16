# bot.py
import logging
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    SIGNAL_EXPIRY_HOURS, REMOVE_HOLD_SIGNALS,
    CRYPTO_PAIRS, FOREX_PAIRS, GOLD_PAIR,
    GEMINI_API_KEY, GROQ_API_KEY, TWELVEDATA_API_KEY,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from strategy import compute_signal

log = logging.getLogger(__name__)

# ============ ACTIVE SIGNALS STORE ============
ACTIVE_SIGNALS: dict[str, dict] = {}   # {symbol: {signal, ts, msg_id, chat_id}}


def save_signal(symbol: str, sig: dict, msg_id: int, chat_id: int):
    ACTIVE_SIGNALS[symbol] = {
        **sig,
        "ts": datetime.utcnow(),
        "msg_id": msg_id,
        "chat_id": chat_id,
    }


def cleanup_signals(bot):
    """6h purane + HOLD signals delete karo."""
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
        try:
            bot.delete_message(chat_id=info["chat_id"], message_id=info["msg_id"])
        except Exception as e:
            log.warning(f"delete fail {sym}: {e}")
        del ACTIVE_SIGNALS[sym]

    if to_remove:
        log.info(f"🧹 Cleaned {len(to_remove)} signals: {to_remove}")


# ============ FORMATTER ============
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


async def send_signal(application, sig: dict, chat_id_override: int = None):
    """Ek signal bhejo aur ACTIVE_SIGNALS me store karo."""
    chat_id = chat_id_override or (int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None)
    if not chat_id:
        log.error("❌ TELEGRAM_CHAT_ID missing — signal not sent")
        return
    try:
        msg = await application.bot.send_message(
            chat_id=chat_id,
            text=format_signal(sig),
            parse_mode="Markdown",
        )
        save_signal(sig["symbol"], sig, msg.message_id, chat_id)
        log.info(f"✅ Sent {sig['symbol']} {sig['signal']} → chat {chat_id}")
    except Exception as e:
        log.error(f"send_signal fail {sig.get('symbol')}: {e}")


# ============ TELEGRAM HANDLERS ============
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
        "🤖 *Signal Bot*\n"
        "Har 5 min auto-analysis on 19 pairs.\n\n"
        "Commands:\n"
        "/start — menu\n"
        "/signal BTCUSDT — manual signal\n"
        "/chatid — apna chat ID lo\n"
        "/status — bot health\n"
        "/test — pipeline test",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu_crypto":
        await q.edit_message_text("Crypto pairs:\n" + "\n".join(CRYPTO_PAIRS))
    elif data == "menu_forex":
        await q.edit_message_text("Forex pairs:\n" + "\n".join(FOREX_PAIRS))
    elif data == "menu_gold":
        await q.edit_message_text(f"Gold: {GOLD_PAIR}")
    elif data == "menu_chatid":
        await q.edit_message_text(f"Your chat ID: `{q.message.chat.id}`", parse_mode="Markdown")
    elif data == "menu_status":
        txt = (
            f"📊 *Bot Status*\n\n"
            f"Chat ID set: {'✅' if TELEGRAM_CHAT_ID else '❌ MISSING'}\n"
            f"Chat ID value: `{TELEGRAM_CHAT_ID or 'None'}`\n"
            f"Your chat ID: `{q.message.chat.id}`\n"
            f"Gemini key: {'✅' if GEMINI_API_KEY else '❌'}\n"
            f"Groq key: {'✅' if GROQ_API_KEY else '❌'}\n"
            f"TwelveData key: {'✅' if TWELVEDATA_API_KEY else '❌'}\n"
            f"Active signals: {len(ACTIVE_SIGNALS)}"
        )
        await q.edit_message_text(txt, parse_mode="Markdown")
    elif data == "menu_test":
        await q.edit_message_text("⏳ Running full pipeline test...")
        try:
            from data_fetcher import fetch_all_pairs_raw
            from ai_analyzer import analyze_all_pairs

            raw = fetch_all_pairs_raw()
            await q.message.reply_text(f"📊 Fetched {len(raw)} pairs. Calling AI...")

            results = analyze_all_pairs(raw)
            await q.message.reply_text(f"✅ AI returned {len(results)} signals. Sending first 3...")

            for sig in results[:3]:
                await send_signal(context.application, sig, chat_id_override=q.message.chat.id)
        except Exception:
            await q.message.reply_text(
                f"❌ Error:\n```\n{traceback.format_exc()[:1000]}\n```",
                parse_mode="Markdown",
            )


async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual /signal SYMBOL"""
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
        await update.message.reply_text(f"❌ {sym} not in supported list.")
        return

    sig = compute_signal(sym, tf_data)
    await update.message.reply_text(format_signal(sig), parse_mode="Markdown")


async def chatid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/chatid — apna chat ID lo"""
    await update.message.reply_text(
        f"Your chat ID: `{update.effective_chat.id}`\n\n"
        f"Railway me `TELEGRAM_CHAT_ID` = `{update.effective_chat.id}` set karo.",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — bot health check"""
    txt = (
        f"📊 *Bot Status*\n\n"
        f"Chat ID set: {'✅' if TELEGRAM_CHAT_ID else '❌ MISSING'}\n"
        f"Chat ID value: `{TELEGRAM_CHAT_ID or 'None'}`\n"
        f"Your chat ID: `{update.effective_chat.id}`\n"
        f"Gemini key: {'✅' if GEMINI_API_KEY else '❌'}\n"
        f"Groq key: {'✅' if GROQ_API_KEY else '❌'}\n"
        f"TwelveData key: {'✅' if TWELVEDATA_API_KEY else '❌'}\n"
        f"Active signals: {len(ACTIVE_SIGNALS)}"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/test — full pipeline manually chalao"""
    await update.message.reply_text("⏳ Testing full pipeline (fetch → AI → send)...")
    try:
        from data_fetcher import fetch_all_pairs_raw
        from ai_analyzer import analyze_all_pairs

        raw = fetch_all_pairs_raw()
        await update.message.reply_text(f"📊 Fetched {len(raw)} pairs. Calling AI...")

        results = analyze_all_pairs(raw)
        await update.message.reply_text(f"✅ AI returned {len(results)} signals. Sending first 3...")

        for sig in results[:3]:
            await send_signal(context.application, sig, chat_id_override=update.effective_chat.id)
    except Exception:
        await update.message.reply_text(
            f"❌ Error:\n```\n{traceback.format_exc()[:1000]}\n```",
            parse_mode="Markdown",
        )


async def autoon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/autoon — auto analysis ON (ye hamesha scheduler se chalta hai)"""
    await update.message.reply_text(
        "✅ Auto-analysis **already ON** hai.\n"
        "Ye har 5 minute me khud chalti hai scheduler se.\n\n"
        "Agar signals nahi aa rahe to:\n"
        "1. `/chatid` se apna ID lo\n"
        "2. Railway Variables me `TELEGRAM_CHAT_ID` set karo\n"
        "3. Redeploy karo\n"
        "4. `/status` bhejo verify karne ke liye",
        parse_mode="Markdown",
    )


async def autooff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/autooff — just info (scheduler band karne ke liye Railway me env change)"""
    await update.message.reply_text(
        "ℹ️ Scheduler hamesha chal raha hai. Band karne ke liye Railway Variables me "
        "`ANALYSIS_INTERVAL_MINUTES=0` set karke redeploy karo.",
        parse_mode="Markdown",
    )


# ============ BUILD APP ============
def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CommandHandler("chatid", chatid_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("autoon", autoon_cmd))
    app.add_handler(CommandHandler("autooff", autooff_cmd))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    return app