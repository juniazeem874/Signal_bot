import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

import config
import data_fetcher as dfetch
import strategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAGE_SIZE = 8  # buttons per page in the pair list


# ---------------------------------------------------------------------
# Menu builders
# ---------------------------------------------------------------------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Crypto (Binance)", callback_data="menu_crypto_0")],
        [InlineKeyboardButton("💱 Forex (TwelveData)", callback_data="menu_forex_0")],
    ]
    return InlineKeyboardMarkup(keyboard)


def paged_pair_keyboard(pairs, category, page):
    start = page * PAGE_SIZE
    chunk = pairs[start:start + PAGE_SIZE]

    buttons = [[InlineKeyboardButton(p, callback_data=f"pair_{category}_{p}")] for p in chunk]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_{category}_{page-1}"))
    if start + PAGE_SIZE < len(pairs):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_{category}_{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------
# Signal formatting + generation
# ---------------------------------------------------------------------

def format_signal_message(symbol: str, result: dict) -> str:
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}[result["signal"]]
    lines = [
        f"{emoji} *{symbol}* — *{result['signal']}*",
        f"Confidence: {result['confidence']}/4 confluence checks",
        f"Price: `{result['price']:.5f}`",
        f"Trend bias (HTF): {result['trend_bias']}",
        "",
        "*Reasons:*",
    ]
    for r in result["reasons"]:
        lines.append(f"• {r}")

    if result["signal"] in ("BUY", "SELL"):
        lines.append("")
        lines.append(f"Stop Loss: `{result['stop_loss']:.5f}`")
        lines.append(f"Take Profit: `{result['take_profit']:.5f}`")

    lines.append("")
    lines.append("_Not financial advice. Always manage your own risk._")
    return "\n".join(lines)


async def generate_and_send_signal(symbol: str, chat_send):
    """chat_send is an async callable like update.message.reply_text or query.edit_message_text"""
    try:
        if dfetch.is_forex_symbol(symbol):
            entry_interval = config.ENTRY_INTERVAL_TWELVEDATA
            trend_interval = config.TREND_INTERVAL_TWELVEDATA
        else:
            entry_interval = config.ENTRY_INTERVAL_BINANCE
            trend_interval = config.TREND_INTERVAL_BINANCE

        entry_df = dfetch.fetch_candles(symbol, entry_interval)
        trend_df = dfetch.fetch_candles(symbol, trend_interval)

        result = strategy.analyze(entry_df, trend_df)
        msg = format_signal_message(symbol, result)
        await chat_send(msg, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Signal generation failed for %s", symbol)
        await chat_send(f"⚠️ Couldn't get a signal for *{symbol}*: {e}", parse_mode="Markdown")


# ---------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Forex & Crypto Signal Bot*\n\n"
        "Pick a market below, or type a pair directly:\n"
        "`/signal BTCUSDT` (crypto)\n"
        "`/signal EUR/USD` (forex)"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/signal BTCUSDT` or `/signal EUR/USD`", parse_mode="Markdown")
        return
    symbol = " ".join(context.args).upper()
    await update.message.reply_text(f"Analyzing {symbol}...")
    await generate_and_send_signal(symbol, update.message.reply_text)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_main":
        await query.edit_message_text("👋 Pick a market:", reply_markup=main_menu_keyboard())
        return

    if data.startswith("menu_crypto_"):
        page = int(data.split("_")[-1])
        pairs = dfetch.get_top_crypto_pairs()
        await query.edit_message_text(
            "💰 Top crypto pairs (by volume). Or use `/signal SYMBOL` for any other pair.",
            reply_markup=paged_pair_keyboard(pairs, "crypto", page),
            parse_mode="Markdown",
        )
        return

    if data.startswith("menu_forex_"):
        page = int(data.split("_")[-1])
        pairs = config.FOREX_PAIRS
        await query.edit_message_text(
            "💱 Forex & metals pairs. Or use `/signal EUR/USD` for any other pair.",
            reply_markup=paged_pair_keyboard(pairs, "forex", page),
            parse_mode="Markdown",
        )
        return

    if data.startswith("pair_"):
        _, category, symbol = data.split("_", 2)
        await query.edit_message_text(f"Analyzing {symbol}...")
        await generate_and_send_signal(symbol, query.edit_message_text)
        return


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send /start to open the menu, or `/signal SYMBOL` for a direct check.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------

def build_app():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    return app
