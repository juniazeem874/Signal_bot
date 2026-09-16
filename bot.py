# bot.py
import logging
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
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from strategy import compute_signal

log = logging.getLogger(__name__)

# ============ ACTIVE SIGNALS STORE ============
ACTIVE_SIGNALS: dict[str, dict] = {}   # {symbol: {signal, ts, msg_id}}


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


async def send_signal(application, sig: dict):
    """Ek signal bhejo aur ACTIVE_SIGNALS me store karo."""
    chat_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
    if not chat_id:
        log.error("TELEGRAM_CHAT_ID missing")
        return
    try:
        msg = await application.bot.send_message(
            chat_id=chat_id,
            text=format_signal(sig),
            parse_mode="Markdown",
        )
        save_signal(sig["symbol"], sig, msg.message_id, chat_id)
    except Exception as e:
        log.error(f"send_signal fail {sig.get('symbol')}: {e}")


# ============ TELEGRAM HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Crypto", callback_data="menu_crypto")],
        [InlineKeyboardButton("Forex",  callback_data="menu_forex")],
        [InlineKeyboardButton("Gold",   callback_data="menu_gold")],
    ]
    await update.message.reply_text(
        "🤖 *Signal Bot*\nHar 5 min auto-analysis on 19 pairs.",
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
    else:
        await q.edit_message_text(f"Gold: {GOLD_PAIR}")


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


# ============ BUILD APP ============
def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    return app