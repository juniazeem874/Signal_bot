import logging
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
import data_fetcher as df_fetcher
import strategy
import ai_analyzer
import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Active Trade Memory Tracker: { "XAU/USD": { "signal": "BUY", "price": 2700, "stop_loss": 2690, ... } }
ACTIVE_OPEN_TRADES = {}


def get_initial_active_chats():
    raw_ids = getattr(config, "AUTO_SIGNAL_CHAT_IDS", [])
    active_set = set()
    for cid in raw_ids:
        try:
            active_set.add(int(cid))
        except (ValueError, TypeError):
            pass
    return active_set


ACTIVE_AUTO_SCAN_CHATS = get_initial_active_chats()


async def post_init(application) -> None:
    commands = [
        BotCommand("start", "Show Exness AI Trading Panel"),
        BotCommand("signal", "Get live AI trade & reasoning (e.g. /signal XAU/USD)"),
        BotCommand("autoon", "Turn ON automated Exness signals & reversal alerts"),
        BotCommand("autooff", "Turn OFF automated signals"),
        BotCommand("active", "View currently tracked active trades"),
        BotCommand("myid", "Get your Telegram Chat ID"),
    ]
    await application.bot.set_my_commands(commands)


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🆔 Your Telegram Chat ID: `{chat_id}`", parse_mode="Markdown")


async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ACTIVE_OPEN_TRADES:
        await update.message.reply_text("ℹ️ No active trades currently tracked.", parse_mode="Markdown")
        return

    msg = "📊 **ACTIVE TRACKED TRADES (EXNESS)**\n\n"
    for sym, tr in ACTIVE_OPEN_TRADES.items():
        emoji = "🟢" if tr['signal'] == "BUY" else "🔴"
        msg += (
            f"{emoji} **{sym} ({tr['signal']})**\n"
            f"• Entry Price: `{tr['price']:.5f}`\n"
            f"• SL: `{tr['stop_loss']:.5f}` | TP: `{tr['take_profit']:.5f}`\n\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def autoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ACTIVE_AUTO_SCAN_CHATS.add(chat_id)
    msg = "🟢 **Auto Signals & Live Reversal Monitoring TURNED ON!**"
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def autooff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ACTIVE_AUTO_SCAN_CHATS.discard(chat_id)
    msg = "🔴 **Auto Signals TURNED OFF!**"
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    is_active = chat_id in ACTIVE_AUTO_SCAN_CHATS
    status_str = "🟢 ON" if is_active else "🔴 OFF"

    toggle_button = (
        InlineKeyboardButton("🔴 Turn OFF Auto Scanner", callback_data="toggle_auto_off")
        if is_active
        else InlineKeyboardButton("🟢 Turn ON Auto Scanner", callback_data="toggle_auto_on")
    )

    keyboard = [
        [toggle_button],
        [
            InlineKeyboardButton("🥇 Gold (XAU/USD)", callback_data="sig_XAU/USD"),
            InlineKeyboardButton("⚡ BTC/USDT", callback_data="sig_BTCUSDT"),
        ],
        [
            InlineKeyboardButton("💶 EUR/USD", callback_data="sig_EUR/USD"),
            InlineKeyboardButton("💷 GBP/USD", callback_data="sig_GBP/USD"),
            InlineKeyboardButton("💴 USD/JPY", callback_data="sig_USD/JPY"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"🧠 **EXNESS INSTITUTIONAL AI TRADING BOT**\n\n"
        f"🤖 **Auto Scanner Status:** `{status_str}`\n"
        f"🎯 **Exness Protection:** Spread Buffer & Slippage Guard Active\n\n"
        f"• Instant Analysis: Click buttons below or `/signal XAU/USD`\n"
        f"• Active Trade List: `/active`\n"
        f"• Auto Scan Control: `/autoon` / `/autooff`"
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(msg, reply_markup=reply_markup, parse_mode="Markdown")


async def process_signal(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
    status_msg = None
    try:
        if update.message:
            status_msg = await update.message.reply_text(f"🧠 Exness AI is analyzing `{symbol}`...", parse_mode="Markdown")
        elif update.callback_query:
            status_msg = await update.callback_query.message.reply_text(f"🧠 Exness AI is analyzing `{symbol}`...", parse_mode="Markdown")

        entry_df, trend_df = df_fetcher.get_data(symbol)

        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            err_text = f"❌ Could not fetch market data for `{symbol}`."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="Markdown")
            return

        analysis = await strategy.analyze(entry_df, trend_df, symbol)
        signal_type = analysis.get("signal", "HOLD")
        price = analysis.get("price", 0.0)

        if signal_type in ["BUY", "SELL"]:
            # Save trade in active tracker
            ACTIVE_OPEN_TRADES[symbol] = {
                "signal": signal_type,
                "price": price,
                "stop_loss": analysis['stop_loss'],
                "take_profit": analysis['take_profit']
            }

            reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
            emoji = "🟢" if signal_type == "BUY" else "🔴"
            out_msg = (
                f"{emoji} **EXNESS {signal_type} SIGNAL: {symbol}**\n\n"
                f"💰 **Entry Price:** `{price:.5f}`\n"
                f"🛑 **Stop Loss (Exness Buffered):** `{analysis['stop_loss']:.5f}`\n"
                f"🎯 **Take Profit:** `{analysis['take_profit']:.5f}`\n"
                f"⚖️ **Risk/Reward:** `1:{analysis['rr_ratio']}`\n\n"
                f"🧠 **TRADE REASONING & BRAIN ANALYSIS:**\n{reasons_text}"
            )
        else:
            reason = analysis['reasons'][0] if analysis.get('reasons') else "No setup found."
            out_msg = (
                f"🟡 **HOLD / NO TRADE: {symbol}**\n\n"
                f"💰 Current Price: `{price:.5f}`\n"
                f"📊 HTF Trend: `{analysis.get('trend_bias', 'neutral').upper()}`\n"
                f"🧠 **AI Reason:** {reason}"
            )

        if status_msg:
            await status_msg.edit_text(out_msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error processing signal for {symbol}: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text(f"⚠️ Couldn't get signal for `{symbol}`: {str(e)}", parse_mode="Markdown")


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Background Job: Scans for NEW Signals AND Monitors ACTIVE Trades for Early Close."""
    if not ACTIVE_AUTO_SCAN_CHATS:
        return

    pairs = getattr(config, "AUTO_SCAN_PAIRS", ["XAU/USD", "BTCUSDT", "EUR/USD"])

    for symbol in pairs:
        try:
            entry_df, trend_df = df_fetcher.get_data(symbol)
            if entry_df is None or entry_df.empty or trend_df is None or trend_df.empty:
                continue

            last_price = entry_df.iloc[-1]["close"]

            # --- STEP 1: MONITOR ACTIVE TRADES FOR REVERSAL OR TP/SL HIT ---
            if symbol in ACTIVE_OPEN_TRADES:
                active_tr = ACTIVE_OPEN_TRADES[symbol]
                sig = active_tr["signal"]
                sl = active_tr["stop_loss"]
                tp = active_tr["take_profit"]

                close_needed = False
                close_reason = ""

                # Check SL / TP Hit physically
                if sig == "BUY":
                    if last_price <= sl:
                        close_needed = True
                        close_reason = "🛑 Stop Loss hit on Exness market."
                    elif last_price >= tp:
                        close_needed = True
                        close_reason = "🎯 Take Profit hit successfully!"
                elif sig == "SELL":
                    if last_price >= sl:
                        close_needed = True
                        close_reason = "🛑 Stop Loss hit on Exness market."
                    elif last_price <= tp:
                        close_needed = True
                        close_reason = "🎯 Take Profit hit successfully!"

                # Check AI Trend Reversal
                if not close_needed:
                    summary = {
                        "last_price": last_price,
                        "htf_bias": ind.get_htf_bias(trend_df),
                        "patterns": [ind.detect_rejection_candle(entry_df), ind.detect_fvg(entry_df)],
                        "volume_status": "High" if ind.has_above_avg_volume(entry_df) else "Normal"
                    }
                    ai_check = await ai_analyzer.check_active_trade_reversal(symbol, active_tr, summary)
                    if ai_check.get("action") == "CLOSE":
                        close_needed = True
                        close_reason = f"⚠️ Market Trend Reversed / Structure Invalidation!\n• {ai_check.get('reason')}"

                # Send Telegram CLOSE ALERT if required
                if close_needed:
                    close_msg = (
                        f"🚨 **EXNESS TRADE ALERT: CLOSE {symbol} IMMEDIATELY** 🚨\n\n"
                        f"📌 **Active Trade:** {sig} at `{active_tr['price']:.5f}`\n"
                        f"💰 **Current Price:** `{last_price:.5f}`\n\n"
                        f"⚠️ **REASON TO CLOSE:**\n{close_reason}"
                    )
                    del ACTIVE_OPEN_TRADES[symbol]  # Remove from active tracking

                    for cid in list(ACTIVE_AUTO_SCAN_CHATS):
                        try:
                            await context.bot.send_message(chat_id=cid, text=close_msg, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(f"Failed sending alert to {cid}: {e}")

            # --- STEP 2: SCAN FOR NEW BUY/SELL SIGNALS ---
            else:
                analysis = await strategy.analyze(entry_df, trend_df, symbol)
                signal_type = analysis.get("signal", "HOLD")

                if signal_type in ["BUY", "SELL"]:
                    price = analysis.get("price", 0.0)
                    reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
                    emoji = "🟢" if signal_type == "BUY" else "🔴"

                    # Save in active memory
                    ACTIVE_OPEN_TRADES[symbol] = {
                        "signal": signal_type,
                        "price": price,
                        "stop_loss": analysis['stop_loss'],
                        "take_profit": analysis['take_profit']
                    }

                    alert_msg = (
                        f"🚨 **AUTOMATED EXNESS AI SIGNAL** 🚨\n\n"
                        f"{emoji} **{signal_type} SIGNAL: {symbol}**\n\n"
                        f"💰 **Entry Price:** `{price:.5f}`\n"
                        f"🛑 **Stop Loss (Exness Buffered):** `{analysis['stop_loss']:.5f}`\n"
                        f"🎯 **Take Profit:** `{analysis['take_profit']:.5f}`\n"
                        f"⚖️ **Risk/Reward:** `1:{analysis['rr_ratio']}`\n\n"
                        f"🧠 **TRADE REASONING & BRAIN ANALYSIS:**\n{reasons_text}"
                    )

                    for cid in list(ACTIVE_AUTO_SCAN_CHATS):
                        try:
                            await context.bot.send_message(chat_id=cid, text=alert_msg, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(f"Failed sending new signal to {cid}: {e}")

        except Exception as e:
            logger.error(f"Auto scan error for {symbol}: {e}")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/signal <SYMBOL>`\nExample: `/signal XAU/USD`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    await process_signal(update, context, symbol)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if data == "toggle_auto_on":
        ACTIVE_AUTO_SCAN_CHATS.add(chat_id)
        await start_command(update, context)
    elif data == "toggle_auto_off":
        ACTIVE_AUTO_SCAN_CHATS.discard(chat_id)
        await start_command(update, context)
    elif data.startswith("sig_"):
        symbol = data.replace("sig_", "")
        await process_signal(update, context, symbol)


def build_app():
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("signal", signal_command))
    application.add_handler(CommandHandler("autoon", autoon_command))
    application.add_handler(CommandHandler("autooff", autooff_command))
    application.add_handler(CommandHandler("active", active_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            auto_scan_job,
            interval=getattr(config, "AUTO_SCAN_INTERVAL", 30),
            first=5
        )

    return application
