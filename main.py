import os
import threading

from flask import Flask
from bot import build_app

# Render's free tier only supports "Web Services" (something that listens on
# a port). Background Workers need a paid plan. This tiny Flask server gives
# Render something to see as "alive" while the real work (Telegram polling)
# runs in the background thread below.
flask_app = Flask(__name__)


@flask_app.route("/")
def health():
    return "Signal bot is running."


def run_flask():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()

    app = build_app()
    print("Bot is starting (polling)...")
    app.run_polling()

