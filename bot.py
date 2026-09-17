# bot.py
import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, MessageHandler, ContextTypes, filters

import config
from config import (
    TELEGRAM_BOT_TOKEN, AUTO_SCAN_INTERVAL, BOT_NAME,
    CRYPTO_PAIRS, FOREX_PAIRS, METAL_PAIRS, GOLD_PAIR,
    SIGNAL_EXPIRY_HOURS, normalize_symbol,
    TELEGRAM_CHAT_IDS, TELEGRAM_CHAT_ID,
)
from data_fetcher import (
    fetch_crypto_multi_tf, fetch_forex_multi_tf, fetch_gold_multi_tf,
    get_current_price,
)
from ai_analyzer import analyze_ready_pairs
from strategies import find_ready_pairs
from signal_tracker import (
    check_all_signals, update_signal_status, remove_signal,
    add_signal_to_tracker, load_tracked_signals,
    log_loss, should_recover, load_recovery_history,
)
from loss_analyzer import (
    analyze_loss, save_loss_analysis,
    load_loss_analyses, get_loss_patterns,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BRAND = "MJ TRADERS"

BACK_LABEL     = "⬅️ Back"
STATUS_LABEL   = "📊 Status"
AUTO_ON_LABEL  = "🟢 Auto ON"
AUTO_OFF_LABEL = "🔴 Auto OFF"

CATEGORIES = {
    "crypto": ("💰 Crypto", CRYPTO_PAIRS),
    "forex":  ("💱 Forex",  FOREX_PAIRS),
    "metals": ("🥇 Gold",   METAL_PAIRS),
}
LABEL_TO_CATEGORY = {label: key for key, (label, _p) in CATEGORIES.items()}
ALL_PAIRS_SET = {p for _l, pairs in CATEGORIES.values() for p in pairs}

DEFAULT_AUTO_ENABLED = getattr(config, "AUTO_SCAN_ENABLED", True)

ACTIVE_SIGNALS = {}
_LAST_SENT_SIGNALS = {}


# ==================== AUTO ON/OFF ====================
def _get_auto_enabled(bot_data, chat_id):
    return bot_data.setdefault("auto_trade_chats", {}).get(chat_id, DEFAULT_AUTO_ENABLED)


def _set_auto_enabled(bot_data, chat_id, value):
    bot_data.setdefault("auto_trade_chats", {})[chat_id] = value


# ==================== SEND HELPERS ====================
def _strip_markdown(text):
    for ch in ("**", "`", "_", "*"):
        text = text.replace(ch, "")
    return text


async def _delete_message_job(context):
    d = context.job.data
    try:
        await context.bot.delete_message(chat_id=d["chat_id"], message_id=d["message_id"])
    except Exception:
        pass


def _schedule_auto_delete(context, chat_id, message_id, hours):
    context.application.job_queue.run_once(
        _delete_message_job, when=hours * 3600,
        data={"chat_id": chat_id, "message_id": message_id},
    )


async def _delete_prev_nav(context, chat_id):
    nav = context.application.bot_data.setdefault("nav_msg", {})
    prev = nav.get(chat_id)
    if prev:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=prev)
        except Exception:
            pass


async def safe_reply(update, context, text, reply_markup=None, track_nav=False,
                     auto_delete_hours=None, delete_prev_nav=None):
    chat_id = update.effective_chat.id
    if delete_prev_nav is None:
        delete_prev_nav = track_nav
    if delete_prev_nav:
        await _delete_prev_nav(context, chat_id)
    try:
        sent = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Markdown reply fail: {e}")
        sent = await update.message.reply_text(_strip_markdown(text), reply_markup=reply_markup)
    if track_nav:
        context.application.bot_data.setdefault("nav_msg", {})[chat_id] = sent.message_id
    if auto_delete_hours:
        _schedule_auto_delete(context, chat_id, sent.message_id, auto_delete_hours)
    return sent


async def _delete_incoming(update, context):
    msg = update.message
    if not msg:
        return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception:
        pass


# ==================== KEYBOARDS ====================
def get_main_keyboard(auto_enabled=True):
    auto_row = [AUTO_OFF_LABEL if auto_enabled else AUTO_ON_LABEL]
    return ReplyKeyboardMarkup(
        [
            [CATEGORIES["crypto"][0], CATEGORIES["forex"][0], CATEGORIES["metals"][0]],
            [STATUS_LABEL] + auto_row,
        ],
        resize_keyboard=True, is_persistent=True,
    )


def pair_menu_keyboard(cat_key):
    _l, pairs = CATEGORIES[cat_key]
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    rows.append([BACK_LABEL])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def _category_of(symbol):
    for k, (_l, pairs) in CATEGORIES.items():
        if symbol in pairs:
            return k
    return "crypto"


# ==================== PRICE FORMAT ====================
def _fmt_price(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == 0:
        return "0"
    abs_v = abs(v)
    if abs_v >= 1000:
        return f"{v:.2f}"
    elif abs_v >= 100:
        return f"{v:.3f}"
    elif abs_v >= 1:
        return f"{v:.4f}"
    elif abs_v >= 0.01:
        return f"{v:.5f}"
    else:
        return f"{v:.8f}"


# ==================== TP CALCULATOR ====================
def _calc_tps(sig):
    entry = float(sig.get("entry", 0) or 0)
    sl = float(sig.get("stop_loss", 0) or 0)
    action = sig.get("signal", "HOLD")

    if entry <= 0 or action == "HOLD":
        return (0, 0, 0, 0)

    if sl <= 0 or sl == entry:
        sl = entry * 0.99 if action == "BUY" else entry * 1.01

    risk = abs(entry - sl)

    if risk > entry * 0.05:
        risk = entry * 0.02
        sl = entry - risk if action == "BUY" else entry + risk

    if risk <= 0:
        return (0, 0, 0, sl)

    if action == "BUY":
        return (entry + risk, entry + risk * 2, entry + risk * 3, sl)
    else:
        return (entry - risk, entry - risk * 2, entry - risk * 3, sl)


# ==================== REASONS FORMATTER ====================
def _format_reasons(sig):
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


def _ensure_price(sig):
    entry = float(sig.get("entry", 0) or 0)
    if entry > 0:
        return sig
    sym = sig.get("symbol", "")
    price = get_current_price(sym)
    if price > 0:
        sig = {**sig, "entry": price}
    return sig


# ==================== SIGNAL FORMAT ====================
def format_signal(sig):
    sig = _ensure_price(sig)
    action = sig.get("signal", "HOLD")
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(action, "⚪")
    entry = float(sig.get("entry", 0) or 0)
    tp1, tp2, tp3, sl = _calc_tps(sig)
    reasons = _format_reasons(sig)

    lines = []
    if sig.get("is_recovery"):
        lines.append("🔄 *RECOVERY SIGNAL* (after recent loss)\n")

    lines += [
        f"{emoji} *{BRAND} — AUTO SIGNAL* {emoji}",
        "",
        f"Pair: *{sig.get('symbol', '?')}*",
        f"Action: *{action}*",
        f"Price: `{_fmt_price(entry)}`",
    ]

    if action != "HOLD" and tp1 > 0 and sl > 0:
        lines += [
            f"TP1 (1:1): `{_fmt_price(tp1)}`",
            f"TP2 (1:2): `{_fmt_price(tp2)}`",
            f"TP3 (1:3): `{_fmt_price(tp3)}`",
            f"Stop Loss (SL): `{_fmt_price(sl)}`",
        ]

    lines += [
        f"Confidence: {sig.get('confidence', 0)}%",
        "",
        "*Reasons (why this trade):*",
        reasons,
    ]

    fib = sig.get("fib_analysis")
    if fib and action != "HOLD":
        lines.append(f"\n📐 *Fib:* {fib}")

    smc = sig.get("smc_analysis")
    if smc and action != "HOLD":
        lines.append(f"🎯 *SMC:* {smc}")

    return "\n".join(lines)


# ==================== SEND SIGNAL ====================
async def send_signal(application, sig, chat_id_override=None):
    # HOLD skip
    if sig.get("signal") == "HOLD":
        logger.info(f"⏭️ Skipping HOLD: {sig.get('symbol')}")
        return

    # Duplicate skip
    symbol = sig.get("symbol")
    signal = sig.get("signal")
    entry = round(float(sig.get("entry", 0) or 0), 6)
    now = datetime.utcnow()

    prev = _LAST_SENT_SIGNALS.get(symbol)
    if prev:
        prev_signal, prev_entry, prev_ts = prev
        age_min = (now - prev_ts).total_seconds() / 60
        same_signal = (prev_signal == signal)
        same_entry = abs(prev_entry - entry) < (entry * 0.001) if entry > 0 else False
        if same_signal and same_entry and age_min < 30:
            logger.info(f"⏭️ Skipping duplicate {symbol} {signal}")
            return

    bot_data = application.bot_data
    if chat_id_override:
        chat_ids = [chat_id_override]
    else:
        active = list(bot_data.get("active_chat_ids", set()))
        chat_ids = [cid for cid in active if _get_auto_enabled(bot_data, cid)]
        if not chat_ids and TELEGRAM_CHAT_IDS:
            chat_ids = TELEGRAM_CHAT_IDS[:]

    if not chat_ids:
        logger.warning(f"⚠️ No subscribers for {symbol}")
        return

    text = format_signal(sig)
    msg_ids = {}
    sent_to = []

    async def _send_one(cid):
        try:
            m = await application.bot.send_message(
                chat_id=cid, text=text, parse_mode="Markdown"
            )
            msg_ids[cid] = m.message_id
            sent_to.append(cid)
        except Exception as e:
            logger.warning(f"❌ send fail {symbol}→{cid}: {e}")

    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])

    if msg_ids:
        ACTIVE_SIGNALS[symbol] = {**sig, "ts": datetime.utcnow(), "msg_ids": msg_ids}
        _LAST_SENT_SIGNALS[symbol] = (signal, entry, now)
        try:
            add_signal_to_tracker({**sig, "telegram_msg_ids": msg_ids})
        except Exception as e:
            logger.warning(f"tracker fail {symbol}: {e}")
        logger.info(f"✅ {symbol} {signal} → {len(sent_to)} chats")


# ==================== CLEANUP ====================
def cleanup_signals(bot):
    now = datetime.utcnow()
    to_remove = [s for s, v in list(ACTIVE_SIGNALS.items())
                 if now - v["ts"] > timedelta(hours=SIGNAL_EXPIRY_HOURS)]
    for sym in to_remove:
        for cid, mid in ACTIVE_SIGNALS[sym].get("msg_ids", {}).items():
            try:
                bot.delete_message(chat_id=cid, message_id=mid)
            except Exception:
                pass
        del ACTIVE_SIGNALS[sym]
    if to_remove:
        logger.info(f"🧹 Cleaned {len(to_remove)} signals")


# ==================== PROCESS OUTCOMES ====================
async def process_signal_outcomes(application):
    """Outcome check + loss analysis + recovery."""
    try:
        outcomes = check_all_signals()
        if not outcomes:
            logger.info("📊 No tracked signals to check")
            return

        logger.info(f"📊 Checking {len(outcomes)} tracked signals")

        bot_data = application.bot_data
        active = list(bot_data.get("active_chat_ids", set()))
        chat_ids = [cid for cid in active if _get_auto_enabled(bot_data, cid)]
        if not chat_ids and TELEGRAM_CHAT_IDS:
            chat_ids = TELEGRAM_CHAT_IDS[:]

        if not chat_ids:
            logger.warning("No subscribers")
            return

        for o in outcomes:
            status = o["status"]
            symbol = o["symbol"]

            if status in ("TP_HIT", "SL_HIT", "REVERSAL"):
                await _send_outcome_message(application, o, chat_ids)

                # Loss analysis
                if status in ("SL_HIT", "REVERSAL"):
                    orig = o.get("original_signal", {})
                    log_loss(symbol, orig, o)

                    analysis = analyze_loss(orig, o)
                    save_loss_analysis(analysis)

                    # Loss deep analysis message
                    await _send_loss_analysis_message(application, analysis, chat_ids)

                update_signal_status(symbol, status)
                remove_signal(symbol)
                logger.info(f"📤 Outcome: {symbol} → {status}")
    except Exception as e:
        logger.error(f"process_signal_outcomes fail: {e}", exc_info=True)


async def _send_outcome_message(application, outcome, chat_ids):
    """Outcome message (TP/SL/Reversal)."""
    symbol = outcome["symbol"]
    status = outcome["status"]
    direction = outcome.get("direction", "?")
    entry = outcome.get("entry", 0)
    current = outcome.get("current_price", 0)
    pnl = outcome.get("pnl_pct", 0)
    tp_level = outcome.get("tp_level", 0)
    age_min = outcome.get("age_min", 0)

    orig = outcome.get("original_signal", {})
    confidence = orig.get("confidence", 0)
    price_move_pct = abs(current - entry) / entry * 100 if entry else 0

    if status == "TP_HIT":