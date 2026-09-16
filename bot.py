# bot.py
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)
from config import (
    TELEGRAM_BOT_TOKEN, SIGNAL_EXPIRY_HOURS,
    BOT_NAME, BOT_TAGLINE,
    CRYPTO_PAIRS, FOREX_PAIRS, GOLD_PAIR,
    normalize_symbol,
    ANALYSIS_INTERVAL_MINUTES,
)
from subscribers import (
    bootstrap_env_ids, subscribe, unsubscribe,
    set_auto_signal, is_auto_signal_on,
    get_signal_subscribers, get_all_subscribers,
    count_subscribers,
)

log = logging.getLogger(__name__)

bootstrap_env_ids()

ACTIVE_SIGNALS: dict[str, dict] = {}


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

    # AI se " • " separated aata hai
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


# ================= SIGNAL FORMAT =================
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


# ================= SEND =================
async def send_signal(application, sig: dict, chat_id_override: int = None):
    if chat_id_override:
        chat_ids = [chat_id_override]
    else:
        chat_ids = get_signal_subscribers()

    if not chat_ids:
        log.warning("No auto-signal subscribers")
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


# ================= /start =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    is_sub = cid in get_all_subscribers()

    if is_sub:
        auto_on = is_auto_signal_on(cid)
        kb = [
            [InlineKeyboardButton(
                "🔴 Auto Signal OFF" if auto_on else "🟢 Auto Signal ON",
                callback_data="toggle_auto",
            )],
            [InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")],
        ]
        status = "🟢 ON" if auto_on else "🔴 OFF"
        await update.message.reply_text(
            f"🤖 *{BOT_NAME}* — {BOT_TAGLINE}\n\n"
            f"Aap subscribed ho ✅\n"
            f"Auto Signal: *{status}*\n"
            f"Interval: every {ANALYSIS_INTERVAL_MINUTES} min\n"
            f"Pairs: {len(CRYPTO_PAIRS) + len(FOREX_PAIRS) + 1}\n\n"
            f"Tap button below to toggle.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
    else:
        kb = [[InlineKeyboardButton("✅ Subscribe", callback_data="subscribe")]]
        await update.message.reply_text(
            f"🤖 *{BOT_NAME}*\n"
            f"_{BOT_TAGLINE}_\n\n"
            f"Auto-scanning *{len(CRYPTO_PAIRS) + len(FOREX_PAIRS) + 1}* pairs "
            f"every *{ANALYSIS_INTERVAL_MINUTES} min*.\n\n"
            f"BUY/SELL alerts — confidence, TP1/TP2/TP3, SL aur detailed reasons ke saath.\n\n"
            f"👉 Subscribe karo signals pane ke liye 👇",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )


# ================= BUTTONS =================
async def button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    cid = q.message.chat.id
    uname = q.from_user.username or q.from_user.first_name or ""

    if data == "subscribe":
        subscribe(cid, uname)
        kb = [
            [InlineKeyboardButton("🔴 Auto Signal OFF", callback_data="toggle_auto")],
            [InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")],
        ]
        await q.edit_message_text(
            f"✅ *Subscribed to {BOT_NAME}!*\n\n"
            f"Auto Signal: *🟢 ON*\n"
            f"Ab signals automatically aayenge — every {ANALYSIS_INTERVAL_MINUTES} min.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
    elif data == "unsubscribe":
        unsubscribe(cid)
        kb = [[InlineKeyboardButton("✅ Subscribe", callback_data="subscribe")]]
        await q.edit_message_text(
            f"❌ *Unsubscribed*\n\n"
            f"Signals band. Wapas subscribe karne ke liye tap karo.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
    elif data == "toggle_auto":
        current = is_auto_signal_on(cid)
        new_state = not current
        set_auto_signal(cid, new_state)
        kb = [
            [InlineKeyboardButton(
                "🔴 Auto Signal OFF" if new_state else "🟢 Auto Signal ON",
                callback_data="toggle_auto",
            )],
            [InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe")],
        ]
        status = "🟢 ON" if new_state else "🔴 OFF"
        await q.edit_message_text(
            f"🤖 *{BOT_NAME}*\n\n"
            f"Auto Signal: *{status}*\n\n"
            f"{'Signals aayenge ✅' if new_state else 'Signals band 🚫'}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )


# ================= BUILD =================
def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_cb))
    return app