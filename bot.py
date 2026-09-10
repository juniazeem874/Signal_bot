import logging
import time
import threading
import telebot
from telebot import types

import config
import data_fetcher
import strategy  # Strategy file jisme market analysis logic ho

# Logging Configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Bot
BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN missing in config.py!")

bot = telebot.TeleBot(BOT_TOKEN)

# Global Bot State
AUTO_TRADE_ENABLED = False
ACTIVE_CHAT_IDS = set()
LAST_SIGNALS = {}  # Duplicate signals se bachne ke liye {symbol: "BUY_time"}

# Default Pairs list (agar config mein Na ho)
DEFAULT_PAIRS = getattr(config, "PAIRS", ["BTCUSDT", "XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"])


def send_signal_to_all(message_text: str):
    """Active chats ko signal notify karta hai."""
    for chat_id in list(ACTIVE_CHAT_IDS):
        try:
            bot.send_message(chat_id, message_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")


def auto_scan_job():
    """Background Auto-Scan Loop jo continuously markets scan karta hai."""
    global AUTO_TRADE_ENABLED

    logger.info("⚡ Background Auto-Scanner Thread Started...")

    while True:
        try:
            if AUTO_TRADE_ENABLED and ACTIVE_CHAT_IDS:
                logger.info("🔍 Scanning markets for entry setups...")

                for symbol in DEFAULT_PAIRS:
                    try:
                        # Fetch Data safely
                        res = data_fetcher.get_data(symbol)

                        # Unpack Safety Check
                        if not isinstance(res, tuple) or len(res) != 2:
                            logger.warning(f"⚠️ Invalid data format for {symbol}")
                            continue

                        entry_df, trend_df = res

                        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
                            logger.warning(f"⚠️ Market data missing/empty for {symbol}")
                            continue

                        # Generate Signal from Strategy
                        # Expected signal format: {"action": "BUY"/"SELL"/"HOLD", "price": 0.0, "tp": 0.0, "sl": 0.0, "reason": "..."}
                        signal = strategy.analyze_market(symbol, entry_df, trend_df)

                        if not signal or signal.get("action") == "HOLD":
                            continue

                        action = signal.get("action")
                        current_time_str = str(entry_df['time'].iloc[-1])
                        signal_key = f"{symbol}_{action}_{current_time_str}"

                        # Prevent sending duplicate signals for the same candle
                        if LAST_SIGNALS.get(symbol) == signal_key:
                            continue

                        LAST_SIGNALS[symbol] = signal_key

                        # Format Signal Notification
                        icon = "🟢" if action == "BUY" else "🔴"
                        msg = (
                            f"{icon} **AUTOMATED TRADE SIGNAL** {icon}\n\n"
                            f"**Pair:** `{symbol}`\n"
                            f"**Action:** `{action}`\n"
                            f"**Entry Price:** `{signal.get('price', 'N/A')}`\n"
                            f"**Take Profit (TP):** `{signal.get('tp', 'N/A')}`\n"
                            f"**Stop Loss (SL):** `{signal.get('sl', 'N/A')}`\n"
                            f"**Reason:** {signal.get('reason', 'Strategy Conditions Met')}\n\n"
                            f"⏱️ _Time: {current_time_str}_"
                        )

                        send_signal_to_all(msg)

                    except Exception as pair_err:
                        logger.error(f"⚠️ Couldn't get signal for {symbol}: {pair_err}")

            # Sleep interval between market scans (60 seconds)
            time.sleep(60)

        except Exception as loop_err:
            logger.error(f"Error in auto_scan_loop: {loop_err}")
            time.sleep(10)


# ==================== TELEGRAM COMMAND HANDLERS ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    ACTIVE_CHAT_IDS.add(message.chat.id)
    welcome_msg = (
        "🤖 **Trading Signal Bot Active**\n\n"
        "Commands:\n"
        "• `/autoon` - Automatic trading signals ON karein\n"
        "• `/autooff` - Automatic trading signals OFF karein\n"
        "• `/signal [PAIR]` - Instant manual signal check karein (e.g. `/signal BTCUSDT`)\n"
        "• `/status` - Bot status dekhein"
    )
    bot.reply_to(message, welcome_msg, parse_mode="Markdown")


@bot.message_handler(commands=['autoon'])
def enable_autotrade(message):
    global AUTO_TRADE_ENABLED
    AUTO_TRADE_ENABLED = True
    ACTIVE_CHAT_IDS.add(message.chat.id)
    bot.reply_to(
        message,
        "✅ **Auto-Trade Mode Activated!**\nBot ab background mein market scan karke alerts bheje ga."
    )


@bot.message_handler(commands=['autooff'])
def disable_autotrade(message):
    global AUTO_TRADE_ENABLED
    AUTO_TRADE_ENABLED = False
    bot.reply_to(message, "🛑 **Auto-Trade Mode Deactivated.**")


@bot.message_handler(commands=['status'])
def check_status(message):
    status_str = "🟢 Active" if AUTO_TRADE_ENABLED else "🔴 Disabled"
    bot.reply_to(
        message,
        f"📊 **Bot Status:**\nAuto-Trade: `{status_str}`\nTracked Pairs: `{len(DEFAULT_PAIRS)}`"
    )


@bot.message_handler(commands=['signal'])
def manual_signal(message):
    """Single pair ka instant signal check karta hai."""
    args = message.text.split()
    symbol = args[1].upper() if len(args) > 1 else "BTCUSDT"

    bot.reply_to(message, f"🔍 Fetching analysis for `{symbol}`...")

    try:
        res = data_fetcher.get_data(symbol)
        if not isinstance(res, tuple) or len(res) != 2:
            bot.reply_to(message, f"❌ Could not fetch valid data for `{symbol}`")
            return

        entry_df, trend_df = res
        if entry_df is None or trend_df is None or entry_df.empty or trend_df.empty:
            bot.reply_to(message, f"❌ Market data empty for `{symbol}`")
            return

        signal = strategy.analyze_market(symbol, entry_df, trend_df)
        action = signal.get("action", "HOLD")

        if action == "HOLD":
            bot.reply_to(message, f"⏸️ **{symbol}:** No trade setup right now (HOLD).")
        else:
            icon = "🟢" if action == "BUY" else "🔴"
            msg = (
                f"{icon} **MANUAL SIGNAL RESULT**\n\n"
                f"**Pair:** `{symbol}`\n"
                f"**Action:** `{action}`\n"
                f"**Entry Price:** `{signal.get('price', 'N/A')}`\n"
                f"**Take Profit (TP):** `{signal.get('tp', 'N/A')}`\n"
                f"**Stop Loss (SL):** `{signal.get('sl', 'N/A')}`"
            )
            bot.reply_to(message, msg, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    logger.info("🚀 Starting Trading Bot...")

    # Start Auto-Scanner in a background daemon thread
    scanner_thread = threading.Thread(target=auto_scan_job, daemon=True)
    scanner_thread.start()

    # Start Telegram Bot Polling
    logger.info("🤖 Bot is polling for Telegram commands...")
    bot.infinity_polling()
