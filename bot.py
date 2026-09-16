# bot.py
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, SIGNAL_EXPIRY_HOURS,
    BOT_NAME, BOT_TAGLINE, ANALYSIS_INTERVAL_MINUTES,
    CRYPTO_PAIRS, FOREX_PAIRS, GOLD_PAIR,
    normalize_symbol,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from ai_analyzer import analyze_all_pairs

log = logging.getLogger(__name__)

# ACTIVE_SIGNALS: {symbol: {"msg_ids": {chat_id: msg_id}, ...}}
ACTIVE_SIGNALS: dict[str, dict] = {}

# ================= REPLY KEYBOARD (Neeche wale buttons) =================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Neeche wala menu — BTCUSDT, ETHUSDT, etc.
    Ye Telegram ke native bottom keyboard me dikhega.
    """
    rows = []
    # Crypto pairs — 2 per row
    crypto = CRYPTO_PAIRS[:8]   # BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX
    for i in range(0, len(crypto), 2):
        row = [KeyboardButton(crypto[i])]
        if i + 1 < len(crypto):
            row.append(KeyboardButton(crypto[i + 1]))
        rows.append(row)
    # Gold + DOGE extra
    rows.append([KeyboardButton("XAUUSD"), KeyboardButton("DOGEUSDT")])
    rows.append([KeyboardButton("⬅️ Back")])
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Pair select karo...",
    )


def save_signal(symbol: str, sig: dict, msg_ids: dict, chat_ids: list):
    ACTIVE_SIGNALS[symbol] = {
        **sig,
        "ts": datetime.utcnow(),
        "msg_ids": msg_ids,
        "chat_ids": chat_ids,
    }


def cleanup_signals(bot):
    """Sirf 6h purane delete — HOLD bhi rahega."""
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
                log.warning(f"delete fail {sym}@{chat_id}: {e}")
        del ACTIVE_SIGNALS[sym]

    if to_remove:
        log.info(f"🧹 Cleaned {len(to_remove)} signals")


# ================= TP CALCULATOR =================
def _calc_tps(sig: dict) -> tuple:
    entry = float(sig.get("entry", 0) or 0)
    sl = float(sig.get("stop_loss", 0) or 0)
    action = sig.get("signal", "HOLD")

    if entry <= 0 or sl <= 0 or action == "HOLD" or entry == sl:
        return (0, 0, 0, sl)

    risk = abs(entry - sl)
    if action == "BUY":
        return (entry + risk, entry + risk * 2, entry + risk * 3, sl)
    else:
        return (entry - risk, entry - risk * 2, entry - risk * 3, sl)


# ================= REASON FORMATTER =================
def _format_reasons(sig: dict) -> str:
    raw = (sig.get("reason") or "").strip()
    if " • " in raw:
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


# ================= SIGNAL FORMAT (MJ TRADERS STYLE) =================
def format_signal(sig: dict) -> str:
    action = sig.get("signal", "HOLD")
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(action, "⚪")
    entry = float(sig.get("entry", 0) or 0)
    tp1, tp2, tp3, sl = _calc_tps(sig)
    reasons = _format_reasons(sig)

    lines = [
        f"{emoji} *{BOT_NAME} — AUTO SIGNAL* {emoji}",
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


# ================= SEND SIGNAL =================
async def send_signal(application, sig: dict, chat_id_override: int = None):
    """Signal bhejo sab registered chats ko."""
    chat_ids = [chat_id_override] if chat_id_override else TELEGRAM_CHAT_IDS
    if not chat_ids:
        log.error("No chat IDs configured")
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

    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])

    if msg_ids:
        save_signal(sig["symbol"], sig, msg_ids, sent_to)
        log.info(f"✅ {sig['symbol']} {sig['signal']} → {len(sent_to)} chats")


# ================= /start — Sirf Keyboard Dikhao =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start pe koi welcome text nahi — sirf neeche wala keyboard.
    """
    await update.message.reply_text(
        "⌨️",
        reply_markup=get_main_keyboard(),
    )


# ================= PAIR CLICK HANDLER =================
async def pair_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Jab user neeche wale keyboard se koi pair click kare,
    to us pair ka analysis fetch karo aur signal bhejo.
    """
    text = update.message.text.strip()
    if text == "⬅️ Back":
        # Back pe keyboard wapas dikhao
        await update.message.reply_text("⌨️", reply_markup=get_main_keyboard())
        return

    sym = normalize_symbol(text)
    if sym not in CRYPTO_PAIRS + FOREX_PAIRS + [GOLD_PAIR]:
        # Unknown text — kuch mat karo
        return

    await update.message.reply_text(f"⏳ Fetching {sym}...")

    try:
        if sym in CRYPTO_PAIRS:
            tf_data = fetch_crypto_multi_tf(sym)
        elif sym in FOREX_PAIRS:
            tf_data = fetch_forex_multi_tf(sym)
        elif sym == GOLD_PAIR:
            tf_data = fetch_gold_multi_tf()
        else:
            return

        results = analyze_all_pairs({sym: tf_data})
        if results:
            await update.message.reply_text(
                format_signal(results[0]), parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ No signal for {sym}")
    except Exception as e:
        log.exception(f"pair_click {sym} failed: {e}")
        await update.message.reply_text(f"❌ Error analyzing {sym}")


# ================= BUILD =================
def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lambda u, c: None))   # placeholder
    # Sirf text messages handle karo (pair clicks)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pair_click_handler))
    return app