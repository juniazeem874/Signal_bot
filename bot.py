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


async def post_init(application) -> None:
    commands = [
        BotCommand("start", "Show all Forex & Crypto pairs menu"),
        BotCommand("signal", "Get signal for any pair (e.g. /signal BTCUSDT)"),
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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
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
        "⚡ **Institutional Scalping Signal Bot**\n\n"
        "• Manual Signal: Click buttons or type `/signal BTCUSDT`\n"
        "• Get Chat ID: `/myid`\n"
        "• Auto-Scanner: Active in background for BUY/SELL setups."
    )
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")


async def process_signal(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str):
    status_msg = None
    try:
        if update.message:
            status_msg = await update.message.reply_text(f"⏳ Analyzing `{symbol}`...", parse_mode="Markdown")
        elif update.callback_query:
            status_msg = await update.callback_query.message.reply_text(f"⏳ Analyzing `{symbol}`...", parse_mode="Markdown")

        entry_df, trend_df = df_fetcher.get_data(symbol)

        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            err_text = f"❌ Could not fetch market data for `{symbol}`."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="Markdown")
            return

        analysis = strategy.analyze(entry_df, trend_df)
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
                f"📋 **Confluences:**\n{reasons_text}"
            )
        elif signal_type == "SELL":
            reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
            out_msg = (
                f"🔴 **SELL SIGNAL: {symbol}**\n\n"
                f"💰 Entry Price: `{price:.5f}`\n"
                f"🛑 Stop Loss: `{analysis['stop_loss']:.5f}`\n"
                f"🎯 Take Profit: `{analysis['take_profit']:.5f}`\n"
                f"⚖️ Risk/Reward: `1:{analysis['rr_ratio']}`\n\n"
                f"📋 **Confluences:**\n{reasons_text}"
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
    """Background task: Scans pairs and sends alerts to ALL registered Chat IDs."""
    chat_ids = getattr(config, "AUTO_SIGNAL_CHAT_IDS", [])
    if not chat_ids:
        return

    pairs = getattr(config, "AUTO_SCAN_PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD"])

    for symbol in pairs:
        try:
            entry_df, trend_df = df_fetcher.get_data(symbol)
            if entry_df is None or entry_df.empty or trend_df is None or trend_df.empty:
                continue

            analysis = strategy.analyze(entry_df, trend_df)
            signal_type = analysis.get("signal", "HOLD")

            # Only alert on BUY or SELL
            if signal_type in ["BUY", "SELL"]:
                last_candle_time = str(entry_df.iloc[-1]["time"])
                cache_key = f"{symbol}_{signal_type}_{last_candle_time}"

                if last_sent_signals.get(symbol) != cache_key:
                    last_sent_signals[symbol] = cache_key

                    price = analysis.get("price", 0.0)
                    reasons_text = "\n".join([f"• {r}" for r in analysis.get("reasons", [])])
                    emoji = "🟢" if signal_type == "BUY" else "🔴"

                    alert_msg = (
                        f"🚨 **AUTOMATED TRADING SIGNAL** 🚨\n\n"
                        f"{emoji} **{signal_type} SIGNAL: {symbol}**\n\n"
                        f"💰 Entry Price: `{price:.5f}`\n"
                        f"🛑 Stop Loss: `{analysis['stop_loss']:.5f}`\n"
                        f"🎯 Take Profit: `{analysis['take_profit']:.5f}`\n"
                        f"⚖️ Risk/Reward: `1:{analysis['rr_ratio']}`\n\n"
                        f"📋 **Confluences:**\n{reasons_text}"
                    )

                    # Send to all users in the chat_ids list
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
    if data.startswith("sig_"):
        symbol = data.replace("sig_", "")
        await process_signal(update, context, symbol)


def build_app():
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("signal", signal_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    if getattr(config, "AUTO_SCAN_ENABLED", True):
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                auto_scan_job,
                interval=getattr(config, "AUTO_SCAN_INTERVAL", 60),
                first=10
            )

    return application
