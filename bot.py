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
    TELEGRAM_CHAT_IDS,
    TELEGRAM_CHAT_ID,
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
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BRAND = "MJ TRADERS"

# ==================== LABELS ====================
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

# ==================== ACTIVE SIGNALS (memory) ====================
ACTIVE_SIGNALS = {}


# ==================== AUTO ON/OFF PER CHAT ====================
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


# ==================== SMART PRICE FORMAT ====================
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

    if entry <= 0 or action == "HOLD" or entry == sl:
        return (0, 0, 0, sl)

    if sl <= 0:
        atr = float(sig.get("atr", 0) or 0)
        if atr <= 0:
            atr = entry * 0.005
        sl = entry - atr * 1.5 if action == "BUY" else entry + atr * 1.5

    risk = abs(entry - sl)
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


# ==================== PRICE GUARANTEE ====================
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

    lines = [
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

    fib_note = sig.get("fib_analysis")
    if fib_note and action != "HOLD":
        lines.append(f"\n📐 *Fib:* {fib_note}")

    smc_note = sig.get("smc_analysis")
    if smc_note and action != "HOLD":
        lines.append(f"🎯 *SMC:* {smc_note}")

    return "\n".join(lines)


# ==================== SEND SIGNAL (HOLD SKIP + TRACKER) ====================
async def send_signal(application, sig, chat_id_override=None):
    """
    Signal bhejo. HOLD skip karo.
    Successful send ke baad signal_tracker me add karo.
    """
    # ⭐ HOLD skip
    if sig.get("signal") == "HOLD":
        logger.info(f"⏭️ Skipping HOLD: {sig.get('symbol')}")
        return

    bot_data = application.bot_data
    if chat_id_override:
        chat_ids = [chat_id_override]
    else:
        active = list(bot_data.get("active_chat_ids", set()))
        chat_ids = [cid for cid in active if _get_auto_enabled(bot_data, cid)]
        if not chat_ids and TELEGRAM_CHAT_IDS:
            chat_ids = TELEGRAM_CHAT_IDS[:]
            logger.info(f"📌 Using {len(chat_ids)} IDs from env: {chat_ids}")

    if not chat_ids:
        logger.warning(f"⚠️ No subscribers for {sig.get('symbol')}")
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
            logger.warning(f"❌ send fail {sig.get('symbol')}→{cid}: {e}")

    await asyncio.gather(*[_send_one(cid) for cid in chat_ids])

    if msg_ids:
        # Memory me track
        ACTIVE_SIGNALS[sig["symbol"]] = {
            **sig, "ts": datetime.utcnow(), "msg_ids": msg_ids,
        }
        # ⭐ File me track (outcome check ke liye)
        try:
            add_signal_to_tracker({**sig, "telegram_msg_ids": msg_ids})
        except Exception as e:
            logger.warning(f"tracker add fail {sig.get('symbol')}: {e}")

        logger.info(f"✅ {sig['symbol']} {sig['signal']} → {len(sent_to)} chats (tracked)")


# ==================== CLEANUP (6h purane) ====================
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


# ==================== ⭐ OUTCOME TRACKING ====================
async def process_signal_outcomes(application):
    """
    Purane signals ka outcome check karo — TP/SL/Reversal detect karo.
    Telegram pe update bhejo. Tracked signals se remove karo.
    """
    try:
        outcomes = check_all_signals()
        if not outcomes:
            logger.info("📊 No tracked signals to check")
            return

        logger.info(f"📊 Checking {len(outcomes)} tracked signals")

        # Recipients
        bot_data = application.bot_data
        active = list(bot_data.get("active_chat_ids", set()))
        chat_ids = [cid for cid in active if _get_auto_enabled(bot_data, cid)]
        if not chat_ids and TELEGRAM_CHAT_IDS:
            chat_ids = TELEGRAM_CHAT_IDS[:]

        if not chat_ids:
            logger.warning("No subscribers for outcome update")
            return

        for o in outcomes:
            status = o["status"]
            symbol = o["symbol"]

            if status in ("TP_HIT", "SL_HIT", "REVERSAL"):
                await _send_outcome_message(application, o, chat_ids)
                update_signal_status(symbol, status)
                remove_signal(symbol)
                logger.info(f"📤 Outcome: {symbol} → {status} ({o.get('pnl_pct', 0)}%)")
            else:
                logger.debug(f"⏳ {symbol} RUNNING (PnL {o.get('pnl_pct', 0)}%)")
    except Exception as e:
        logger.error(f"process_signal_outcomes fail: {e}", exc_info=True)


async def _send_outcome_message(application, outcome, chat_ids):
    """Ek outcome ka message bhejo (TP/SL/Reversal)."""
    symbol = outcome["symbol"]
    status = outcome["status"]
    direction = outcome.get("direction", "?")
    entry = outcome.get("entry", 0)
    current = outcome.get("current_price", 0)
    pnl = outcome.get("pnl_pct", 0)
    tp_level = outcome.get("tp_level", 0)

    if status == "TP_HIT":
        emoji = "🎯"
        header = f"{emoji} *{BRAND} — TP HIT* {emoji}"
        detail = f"TP{tp_level if tp_level else 1} HIT ✅  (+{pnl}%)"
        note = "🧠 *AI Note:* Setup worked. Same conditions will be favored for future signals."
    elif status == "SL_HIT":
        emoji = "🛑"
        header = f"{emoji} *{BRAND} — SL HIT* {emoji}"
        detail = f"Stop Loss Hit ❌  ({pnl}%)"
        note = "🧠 *AI Note:* Analyzing what went wrong. Will be more cautious on next setup."
    else:  # REVERSAL
        emoji = "⚠️"
        header = f"{emoji} *{BRAND} — SIGNAL REMOVED* {emoji}"
        detail = "Market Reversal Detected ⚠️\nSignal *REMOVED* — market moving against position"
        note = "🧠 *AI Note:* Market conditions changed. Position invalidated."

    text = (
        f"{header}\n\n"
        f"Pair: *{symbol}*\n"
        f"Action: *{direction}*\n"
        f"Entry: `{_fmt_price(entry)}`\n"
        f"Current: `{_fmt_price(current)}`\n"
        f"{detail}\n\n"
        f"{note}"
    )

    for cid in chat_ids:
        try:
            await application.bot.send_message(
                chat_id=cid, text=text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"outcome send fail {symbol}→{cid}: {e}")


# ==================== MANUAL ANALYSIS ====================
async def _run_analysis(symbol):
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

        # Strategy filter (manual = lower threshold)
        ready = find_ready_pairs({symbol: tf_data}, min_score=2)
        if not ready:
            return f"🟡 *{symbol}* — No clear setup right now"

        results = analyze_ready_pairs(ready)
        if not results:
            return f"⚠️ AI analysis failed for `{symbol}`."
        return format_signal(results[0])
    except Exception as e:
        logger.error(f"_run_analysis crashed {symbol}: {e}", exc_info=True)
        return f"⚠️ Analysis failed for `{symbol}`: {e}"


# ==================== STATUS ====================
def _key_status(name, v):
    return "✅" if v else "❌ MISSING"


async def check_status(update, context):
    await _delete_incoming(update, context)
    bd = context.application.bot_data
    cid = update.effective_chat.id
    enabled = _get_auto_enabled(bd, cid)
    tracked = load_tracked_signals()

    msg = (
        f"📊 *{BRAND} — Status*\n"
        f"Auto: {'🟢 Active' if enabled else '🔴 Disabled'}\n"
        f"Interval: {AUTO_SCAN_INTERVAL // 60} min\n"
        f"Pairs: {len(ALL_PAIRS_SET)}\n"
        f"Signal expiry: {SIGNAL_EXPIRY_HOURS}h\n"
        f"Tracked signals: {len(tracked)}\n"
        f"Your chat ID: `{cid}`\n"
        f"Env chat IDs: `{TELEGRAM_CHAT_IDS}`\n\n"
        f"Gemini: {_key_status('GEMINI', getattr(config, 'GEMINI_API_KEY', ''))}\n"
        f"Groq: {_key_status('GROQ', getattr(config, 'GROQ_API_KEY', ''))}\n"
        f"TwelveData: {_key_status('TD', getattr(config, 'TWELVEDATA_API_KEY', ''))}"
    )
    await safe_reply(update, context, msg, reply_markup=get_main_keyboard(enabled), track_nav=True)


# ==================== WELCOME ====================
async def send_welcome(update, context):
    await _delete_incoming(update, context)
    bd = context.application.bot_data
    cid = update.effective_chat.id
    bd.setdefault("active_chat_ids", set()).add(cid)
    _set_auto_enabled(bd, cid, True)
    msg = (
        f"🤖 *{BRAND}*\n"
        f"Trading Signal Bot\n\n"
        f"Auto-scanning every `{AUTO_SCAN_INTERVAL // 60} min` — "
        f"BUY/SELL alerts with Fibonacci + SMC.\n"
        f"HOLD signals are not sent.\n"
        f"TP/SL outcomes tracked automatically.\n\n"
        f"Your chat ID: `{cid}`\n\n"
        "👇 Menu se category chunein, phir pair pe tap karein."
    )
    await safe_reply(update, context, msg, reply_markup=get_main_keyboard(True), track_nav=True)


# ==================== TEXT HANDLER ====================
async def handle_menu_text(update, context):
    text = (update.message.text or "").strip()
    await _delete_incoming(update, context)
    bd = context.application.bot_data
    cid = update.effective_chat.id
    bd.setdefault("active_chat_ids", set()).add(cid)

    if text.startswith("/start") or text.startswith("/help"):
        await send_welcome(update, context); return
    if text.startswith("/status"):
        await check_status(update, context); return
    if text.startswith("/chatid") or text.startswith("/id"):
        await safe_reply(update, context,
                         f"Your chat ID: `{cid}`\n\n"
                         f"Railway me `TELEGRAM_CHAT_IDS` me add karo (comma-separated).",
                         parse_mode="Markdown")
        return
    if text.startswith("/signals"):
        # Tracked signals dekhne ke liye
        tracked = load_tracked_signals()
        if not tracked:
            await safe_reply(update, context, "📭 No tracked signals currently.", track_nav=True)
            return
        lines = [f"📋 *{len(tracked)} Active Signals:*\n"]
        for s in tracked:
            lines.append(
                f"• *{s['symbol']}* {s['signal']} — entry `{_fmt_price(s['entry'])}` "
                f"({s.get('status', 'ACTIVE')})"
            )
        await safe_reply(update, context, "\n".join(lines), track_nav=True)
        return
    if text == BACK_LABEL:
        await safe_reply(update, context, f"🤖 {BRAND} — choose a category:",
                         reply_markup=get_main_keyboard(_get_auto_enabled(bd, cid)), track_nav=True)
        return
    if text == STATUS_LABEL:
        await check_status(update, context); return
    if text in (AUTO_ON_LABEL, AUTO_OFF_LABEL):
        on = text == AUTO_ON_LABEL
        _set_auto_enabled(bd, cid, on)
        m = "✅ *Auto-Trade Activated!*" if on else "🛑 *Auto-Trade Deactivated.*"
        await safe_reply(update, context, m, reply_markup=get_main_keyboard(on), track_nav=True)
        return
    if text in LABEL_TO_CATEGORY:
        ck = LABEL_TO_CATEGORY[text]
        lbl, _ = CATEGORIES[ck]
        await safe_reply(update, context, f"{lbl} — pick a pair:",
                         reply_markup=pair_menu_keyboard(ck), track_nav=True)
        return

    sym = normalize_symbol(text)
    if sym in ALL_PAIRS_SET:
        ck = _category_of(sym)
        await safe_reply(update, context, f"🔍 Analyzing `{sym}`...", track_nav=True)
        msg = await _run_analysis(sym)
        await safe_reply(update, context, msg, reply_markup=pair_menu_keyboard(ck),
                         track_nav=False, delete_prev_nav=True,
                         auto_delete_hours=SIGNAL_EXPIRY_HOURS)
        return
    await send_welcome(update, context)


# ==================== BUILD APP ====================
def build_app():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN missing!")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.bot_data["active_chat_ids"] = set()
    app.bot_data["auto_trade_chats"] = {}
    app.bot_data["nav_msg"] = {}
    app.add_handler(MessageHandler(filters.TEXT, handle_menu_text))
    return app