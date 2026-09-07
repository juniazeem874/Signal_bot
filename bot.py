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
import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Cache to avoid duplicate notifications on the same candle
last_sent_signals = {}

# Runtime Global State for Auto Signal (Default comes from config)
AUTO_SCAN_ACTIVE = getattr(config, "AUTO_SCAN_ENABLED", True)


async def post_init(application) -> None:
    commands = [
        BotCommand("start", "Show Forex & Crypto pairs & Auto-Signal control"),
        BotCommand("signal", "Get signal for any pair (e.g. /signal BTCUSDT)"),
        BotCommand("autoon", "Turn ON automated background signals"),
        BotCommand("autooff", "Turn OFF automated background signals"),
        BotCommand("myid", "Get your Telegram Chat ID for auto signals"),
    ]
    await application.bot.set_my_commands(commands)


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utility command to get user's Chat ID for config.py / Railway"""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🆔 Your Telegram Chat ID: `{chat_id}`\n\nAdd this ID to Railway `AUTO_SIGNAL_CHAT_ID` variable.",
        parse_mode="Markdown"
    )


async def autoon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to enable Auto Signals"""
    global AUTO_SCAN_ACTIVE
    AUTO_SCAN_ACTIVE = True
    msg = "🟢 **Auto Signals TURNED ON!**\n\nBackground scanner is now actively monitoring pairs for BUY/SELL setups."
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown")


async def autooff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to disable Auto Signals"""
    global AUTO_SCAN_ACTIVE
    AUTO_SCAN_ACTIVE = False
    msg = "🔴 **Auto Signals TURNED OFF!**\n\nAutomated background alerts are paused. Manual `/signal` and buttons will still work normally."
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_str = "🟢 ON" if AUTO_SCAN_ACTIVE else "🔴 OFF"
    toggle_button = (
        InlineKeyboardButton("🔴 Turn OFF Auto Signal", callback_data="toggle_auto_off")
        if AUTO_SCAN_ACTIVE
        else InlineKeyboardButton("🟢 Turn ON Auto Signal", callback_data="toggle_auto_on")
    )

    keyboard = [
        [toggle_button],
        [
            InlineKeyboardButton("⚡ BTC/USDT", callback_data="sig_BTCUSDT"),
            InlineKeyboardButton("💎 ETH/USDT", callback_data="sig_ETHUSDT"),
            InlineKeyboardButton("🚀 SOL/USDT", callback_data="sig_SOLUSDT"),
        ],
        [
            InlineKeyboardButton("🥇 XAU/USD (Gold)", callback_data="sig_XAU/USD"),
            InlineKeyboardButton("💶 EUR/USD", callback_data="sig_EUR/USD"),
            InlineKeyboardButton("💷 GBP/USD", callback_data="sig_GBP/USD"),
        ],
        [
            InlineKeyboardButton("💴 USD/JPY", callback_data="sig_USD/JPY"),
            InlineKeyboardButton("🇨🇦 USD/CAD", callback_data="sig_USD/CAD"),
            InlineKeyboardButton("🇦🇺 AUD/USD", callback_data="sig_AUD/USD"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = (
        f"⚡ **Institutional AI Scalping Bot**\n\n"
        f"🤖 **Auto-Signal Status:** `{status_str}`\n\n"
        f"• Toggle Auto Signal: Use buttons above or `/autoon` / `/autooff`\n"
        f"• Manual Check: Click pair buttons or type `/signal BTCUSDT`\n"
        f"• Get Chat ID: `/myid`"
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(msg, reply_markup=reply_markup, parse_mode="Markdown")


async def process_signal(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
    """Always works for manual checks regardless of Auto-Signal ON/OFF status."""
    status_msg = None
    try:
        if update.message:
            status_msg = await update.message.reply_text(f"⏳ Analyzing `{symbol}` with AI...", parse_mode="Markdown")
        elif update.callback_query:
            status_msg = await update.callback_query.message.reply_text(f"⏳ Analyzing `{symbol}` with AI...", parse_mode="Markdown")

        entry_df, trend_df = df_fetcher.get_data(symbol)

        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            err_text = f"❌ Could not fetch market data for `{symbol}`."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="Markdown")
            return

        # FIXED: Added await here
        analysis = await strategy.analyze(entry_df, trend_df, symbol)
        signal_type = analysis.get("signal", "HOLD")
        price = analysis.get("price", 0.0)

        if signal_type == "BUY":
            reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
            out_msg = (
                f"🟢 **BUY SIGNAL: {symbol}**\n\n"
                f"💰 Entry Price: `{price:.5f}`\n"
                f"🛑 Stop Loss: `{analysis['stop_loss']:.5f}`\n"
                f"🎯 Take Profit: `{analysis['take_profit']:.5f}`\n"
                f"⚖️ Risk/Reward: `1:{analysis['rr_ratio']}`\n\n"
                f"📋 **Analysis:**\n{reasons_text}"
            )
        elif signal_type == "SELL":
            reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
            out_msg = (
                f"🔴 **SELL SIGNAL: {symbol}**\n\n"
                f"💰 Entry Price: `{price:.5f}`\n"
                f"🛑 Stop Loss: `{analysis['stop_loss']:.5f}`\n"
                f"🎯 Take Profit: `{analysis['take_profit']:.5f}`\n"
                f"⚖️ Risk/Reward: `1:{analysis['rr_ratio']}`\n\n"
                f"📋 **Analysis:**\n{reasons_text}"
            )
        else:
            reason = analysis['reasons'][0] if analysis.get('reasons') else "No setup found."
            out_msg = (
                f"🟡 **HOLD / NO SETUP: {symbol}**\n\n"
                f"💰 Current Price: `{price:.5f}`\n"
                f"📊 HTF Trend: `{analysis.get('trend_bias', 'neutral').upper()}`\n"
                f"ℹ️ {reason}"
            )

        if status_msg:
            await status_msg.edit_text(out_msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error processing signal for {symbol}: {e}", exc_info=True)
        if status_msg:
            await status_msg.edit_text(f"⚠️ Couldn't get signal for `{symbol}`: {str(e)}", parse_mode="Markdown")


async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task: Only runs if AUTO_SCAN_ACTIVE is True."""
    global AUTO_SCAN_ACTIVE
    if not AUTO_SCAN_ACTIVE:
        return

    chat_ids = getattr(config, "AUTO_SIGNAL_CHAT_IDS", [])
    if not chat_ids:
        return

    pairs = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD"])

    for symbol in pairs:
        try:
            if not AUTO_SCAN_ACTIVE:
                break

            entry_df, trend_df = df_fetcher.get_data(symbol)
            if entry_df is None or entry_df.empty or trend_df is None or trend_df.empty:
                continue

            # FIXED: Added await here
            analysis = await strategy.analyze(entry_df, trend_df, symbol)
            signal_type = analysis.get("signal", "HOLD")

            if signal_type in ["BUY", "SELL"]:
                last_candle_time = str(entry_df.iloc[-1]["time"])
                cache_key = f"{symbol}_{signal_type}_{last_candle_time}"

                if last_sent_signals.get(symbol) != cache_key:
                    last_sent_signals[symbol] = cache_key

                    price = analysis.get("price", 0.0)
                    reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
                    emoji = "🟢" if signal_type == "BUY" else "🔴"

                    alert_msg = (
                        f"🚨 **AUTOMATED AI TRADING SIGNAL** 🚨\n\n"
                        f"{emoji} **{signal_type} SIGNAL: {symbol}**\n\n"
                        f"💰 Entry Price: `{price:.5f}`\n"
                        f"🛑 Stop Loss: `{analysis['stop_loss']:.5f}`\n"
                        f"🎯 Take Profit: `{analysis['take_profit']:.5f}`\n"
                        f"⚖️ Risk/Reward: `1:{analysis['rr_ratio']}`\n\n"
                        f"📋 **Analysis:**\n{reasons_text}"
                    )

                    for cid in chat_ids:
                        try:
                            await context.bot.send_message(chat_id=cid, text=alert_msg, parse_mode="Markdown")
                        except Exception as send_err:
                            logger.error(f"Failed to send alert to chat_id {cid}: {send_err}")

        except Exception as e:
            logger.error(f"Auto scan error for {symbol}: {e}")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/signal <SYMBOL>`\nExample: `/signal BTCUSDT`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    await process_signal(update, context, symbol)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "toggle_auto_on":
        global AUTO_SCAN_ACTIVE
        AUTO_SCAN_ACTIVE = True
        await start_command(update, context)
    elif data == "toggle_auto_off":
        AUTO_SCAN_ACTIVE = False
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
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            auto_scan_job,
            interval=getattr(config, "AUTO_SCAN_INTERVAL", 60),
            first=10
        )

    return application
