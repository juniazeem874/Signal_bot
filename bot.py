# bot.py
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, SIGNAL_EXPIRY_HOURS,
    BOT_NAME, ANALYSIS_INTERVAL_MINUTES,
    CRYPTO_PAIRS, FOREX_PAIRS, GOLD_PAIR, normalize_symbol,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
)
from ai_analyzer import analyze_all_pairs

log = logging.getLogger(__name__)

ACTIVE_SIGNALS: dict[str, dict] = {}

# ================= REPLY KEYBOARD (Neeche wale buttons) =================
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Neeche wala menu — pair buttons + inline actions merged.
    """
    rows = [
        [KeyboardButton("BTCUSDT"), KeyboardButton("ETHUSDT")],
        [KeyboardButton("SOLUSDT"), KeyboardButton("BNBUSDT")],
        [KeyboardButton("XRPUSDT"), KeyboardButton("ADAUSDT")],
        [KeyboardButton("DOGEUSDT"), KeyboardButton("AVAXUSDT")],
        [KeyboardButton("XAUUSD"),  KeyboardButton("XAU/USD")],
        [KeyboardButton("🔄 Refresh"), KeyboardButton("❓ Help")],
        [KeyboardButton("⬅️ Back")],
    ]
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, one_time_keyboard=False,
        input_field_placeholder="Pair select karo...",
    )


def save_signal(symbol: str, sig: dict, msg_ids: dict, chat_ids: list):
    ACTIVE_SIGNALS[symbol] = {
        **sig, "ts": datetime.utcnow(),
        "msg_ids": msg_ids, "chat_ids": chat_ids,
    }


def cleanup_signals(bot):
    now = datetime.utcnow()
    to_remove = [s for s, v in ACTIVE_SIGNALS.items()
                 if now - v["ts"] > timedelta(hours=SIGNAL_EXPIRY_HOURS)]
    for sym in to_remove:
        for cid, mid in ACTIVE_SIGNALS[sym].get("msg_ids", {}).items():
            try:
                bot.delete_message(chat_id=cid, message_id=mid)
            except Exception as e:
                log.warning(f"delete fail {sym}@{cid}: {e}")
        del ACTIVE_SIGNALS[sym]
    if to_remove:
        log.info(f"🧹 Cleaned {len(to_remove)} signals")


# ================= TP / REASONS =================
def _calc_tps(sig: dict) -> tuple:
    entry = float(sig.get("entry", 0) or 0)
    sl = float(sig.get("stop_loss", 0) or 0)
    action = sig.get("signal", "HOLD")
    if entry <= 0 or sl <= 0 or action == "HOLD" or entry == sl:
        return (0, 0, 0, sl)
    risk = abs(entry - sl)
    if action == "BUY":
        return (entry + risk, entry + risk * 2, entry + risk * 3, sl)
    return (entry - risk, entry - risk * 2, entry - risk * 3, sl)


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
    chat_ids = [chat_id_override] if chat_id_override else TELEGRAM_CHAT_IDS
    if not chat_ids:
        log.error("No chat IDs configured")
        return
    text = format_signal(sig)
    msg_ids, sent_to = {}, []

    async def _send_one(cid: int):
        try:
            m = await application.bot.send_message(
                chat_id=cid, text=text, parse_mode="Markdown")
            msg_ids[cid] = m.message_id
            sent_to.append(cid)
        except Exception as e:
            log.warning(f"send fail {sig['symbol']}→{cid}: {e}")

    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])
    if msg_ids:
        save_signal(sig["symbol"], sig, msg_ids, sent_to)
        log.info(f"✅ {sig['symbol']} {sig['signal']} → {len(sent_to)} chats")


# ================= /start — Keyboard Dikhao =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *{BOT_NAME}* — ready.\n"
        f"Pair select karo neeche se.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


# ================= TEXT HANDLER (Buttons + Unknown) =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    # ===== BACK =====
    if text == "⬅️ Back":
        await update.message.reply_text(
            "🏠 Main menu",
            reply_markup=get_main_keyboard(),
        )
        return

    # ===== REFRESH =====
    if text == "🔄 Refresh":
        await update.message.reply_text(
            "🔄 Menu refreshed.",
            reply_markup=get_main_keyboard(),
        )
        return

    # ===== HELP =====
    if text == "❓ Help":
        await update.message.reply_text(
            f"🤖 *{BOT_NAME}*\n\n"
            f"• Pair button tap karo → us pair ka signal\n"
            f"• Har {ANALYSIS_INTERVAL_MINUTES} min auto-signal aayega\n"
            f"• Signals {SIGNAL_EXPIRY_HOURS}h baad auto-delete honge\n\n"
            f"Supported pairs:\n"
            f"Crypto: {', '.join(CRYPTO_PAIRS)}\n"
            f"Forex: {', '.join(FOREX_PAIRS)}\n"
            f"Gold: {GOLD_PAIR}",
            parse_mode="Markdown",
        )
        return

    # ===== PAIR CLICK =====
    sym = normalize_symbol(text)
    valid = CRYPTO_PAIRS + FOREX_PAIRS + [GOLD_PAIR]
    if sym not in valid:
        # Unknown text — ignore quietly
        return

    await update.message.reply_text(f"⏳ Fetching {sym}...")

    try:
        if sym in CRYPTO_PAIRS:
            tf_data = fetch_crypto_multi_tf(sym)
        elif sym in FOREX_PAIRS:
            tf_data = fetch_forex_multi_tf(sym)
        else:
            tf_data = fetch_gold_multi_tf()

        results = analyze_all_pairs({sym: tf_data})
        if results:
            await update.message.reply_text(
                format_signal(results[0]), parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ No signal for {sym}")
    except Exception as e:
        log.exception(f"pair_click {sym} failed: {e}")
        await update.message.reply_text(f"❌ Error analyzing {sym}")


# ================= BUILD =================
def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT, text_handler))
    return app