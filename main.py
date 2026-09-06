from bot import build_app

if __name__ == "__main__":
    app = build_app()
    print("Bot is starting (polling)...")
    app.run_polling()
