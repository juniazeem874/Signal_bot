import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

import config
import data_fetcher as dfetch
import strategy
import backtest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAGE_SIZE = 8


# ---------------------------------------------------------------------
# Keyboards & Menus
# ---------------------------------------------------------------------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("💰 Crypto (Binance)", callback_data="menu_crypto_0")],
        [InlineKeyboardButton("💱 Forex & Metals (TwelveData)", callback_data="menu_forex_0")],
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


def signal_action_keyboard(symbol):
    keyboard = [
        [InlineKeyboardButton(f"📊 Run Backtest ({symbol})", callback_data=f"backtest_{symbol}")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------------------------------------------------------------
# Formatting Functions
# ---------------------------------------------------------------------

def format_signal_message(symbol: str, result: dict) -> str:
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}[result["signal"]]
    lines = [
        f"{emoji} *{symbol}* — *{result['signal']}*",
        f"⚡ *Strategy:* Fakeout & Confluence Scalper",
        f"Score: `{result['confidence']}/4`",
        f"Price: `{result['price']:.5f}`",
        f"HTF Trend: `{result['trend_bias'].upper()}`",
        "",
        "*Confluence Factors:*",
    ]
    for r in result["reasons"]:
        lines.append(f"• {r}")

    if result["signal"] in ("BUY", "SELL"):
        lines.append("")
        lines.append(f"🛑 *Stop Loss:* `{result['stop_loss']:.5f}`")
        lines.append(f"🎯 *Take Profit:* `{result['take_profit']:.5f}`")

    return "\n".join(lines)


def format_backtest_message(symbol: str, trades: list) -> str:
    if not trades:
        return f"📊 *Backtest Report for {symbol}*\n\nNo trades were triggered in the historical dataset."

    n = len(trades)
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    win_rate = (len(wins) / n) * 100

    gross_profit = sum(t["r_multiple"] for t in wins)
    gross_loss = abs(sum(t["r_multiple"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0

    total_r = sum(t["r_multiple"] for t in trades)

    return (
        f"📊 *Backtest Report: {symbol}*\n\n"
        f"• *Total Trades:* `{n}`\n"
        f"• *Wins / Losses:* `{len(wins)} / {len(losses)}`\n"
        f"• *Win Rate:* `{win_rate:.1f}%`\n"
        f"• *Profit Factor:* `{profit_factor:.2f}`\n"
        f"• *Total Return:* `{total_r:.2f} R`\n\n"
        f"_Simulated on last 500 candles (1m/15m timeframes)._"
    )


# ---------------------------------------------------------------------
# Signal & Backtest Logic
# ---------------------------------------------------------------------

async def generate_and_send_signal(symbol: str, update_or_query):
    try:
        if dfetch.is_forex_symbol(symbol):
            entry_interval = config.ENTRY_INTERVAL_TWELVEDATA
            trend_interval = config.TREND_INTERVAL_TWELVEDATA
        else:
            entry_interval = config.ENTRY_INTERVAL_BINANCE
            trend_interval = config.TREND_INTERVAL_BINANCE

        entry_df = dfetch.fetch_candles(symbol, entry_interval, limit=config.CANDLE_LIMIT)
        trend_df = dfetch.fetch_candles(symbol, trend_interval, limit=config.CANDLE_LIMIT)

        result = strategy.analyze(entry_df, trend_df)
        msg = format_signal_message(symbol, result)
        reply_markup = signal_action_keyboard(symbol)

        if hasattr(update_or_query, "edit_message_text"):
            await update_or_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await update_or_query.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.exception("Signal generation failed for %s", symbol)
        err_text = f"⚠️ Couldn't get signal for *{symbol}*: {e}"
        if hasattr(update_or_query, "edit_message_text"):
            await update_or_query.edit_message_text(err_text, parse_mode="Markdown")
        else:
            await update_or_query.reply_text(err_text, parse_mode="Markdown")


async def execute_telegram_backtest(symbol: str, update_or_query):
    try:
        is_forex = dfetch.is_forex_symbol(symbol)
        entry_interval = config.ENTRY_INTERVAL_TWELVEDATA if is_forex else config.ENTRY_INTERVAL_BINANCE
        trend_interval = config.TREND_INTERVAL_TWELVEDATA if is_forex else config.TREND_INTERVAL_BINANCE

        trades = backtest.run_backtest(symbol, entry_interval, trend_interval, limit=500, max_hold=60)
        report = format_backtest_message(symbol, trades)

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_main")]])

        if hasattr(update_or_query, "edit_message_text"):
            await update_or_query.edit_message_text(report, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await update_or_query.reply_text(report, parse_mode="Markdown", reply_markup=keyboard)

    except Exception as e:
        logger.exception("Backtest failed for %s", symbol)
        err_text = f"⚠️ Backtest failed for *{symbol}*: {e}"
        if hasattr(update_or_query, "edit_message_text"):
            await update_or_query.edit_message_text(err_text, parse_mode="Markdown")
        else:
            await update_or_query.reply_text(err_text, parse_mode="Markdown")


# ---------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Trading Signal & Backtest Bot*\n\n"
        "Select a market below or run direct commands:\n"
        "• `/signal BTCUSDT` or `/signal EUR/USD`\n"
        "• `/backtest BTCUSDT` or `/backtest EUR/USD`"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/signal BTCUSDT` or `/signal EUR/USD`", parse_mode="Markdown")
        return
    symbol = " ".join(context.args).upper()
    await update.message.reply_text(f"Analyzing {symbol}...")
    await generate_and_send_signal(symbol, update.message)


async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/backtest BTCUSDT` or `/backtest EUR/USD`", parse_mode="Markdown")
        return
    symbol = " ".join(context.args).upper()
    await update.message.reply_text(f"Running historical backtest for {symbol}...")
    await execute_telegram_backtest(symbol, update.message)


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
            "💰 Top crypto pairs:",
            reply_markup=paged_pair_keyboard(pairs, "crypto", page),
            parse_mode="Markdown",
        )
        return

    if data.startswith("menu_forex_"):
        page = int(data.split("_")[-1])
        pairs = config.FOREX_PAIRS
        await query.edit_message_text(
            "💱 Forex & metals pairs:",
            reply_markup=paged_pair_keyboard(pairs, "forex", page),
            parse_mode="Markdown",
        )
        return

    if data.startswith("pair_"):
        _, category, symbol = data.split("_", 2)
        await query.edit_message_text(f"Analyzing {symbol}...")
        await generate_and_send_signal(symbol, query)
        return

    if data.startswith("backtest_"):
        symbol = data.split("_", 1)[1]
        await query.edit_message_text(f"Running backtest for {symbol}...")
        await execute_telegram_backtest(symbol, query)
        return


async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send /start to open the menu, `/signal SYMBOL` for analysis, or `/backtest SYMBOL` for historical tests.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------
# App Builder
# ---------------------------------------------------------------------

def build_app():
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("backtest", backtest_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))
    return app
