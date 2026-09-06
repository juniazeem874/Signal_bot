# Forex & Crypto Signal Bot

Telegram bot that gives BUY / SELL / HOLD signals for crypto (Binance) and
forex/metals (TwelveData) using a confluence strategy: trend (EMA50/200),
SMC (Break of Structure + Fair Value Gap), Fibonacci retracement zone, and
volume confirmation. A signal only fires when at least 3 of 4 conditions
line up — otherwise the bot says HOLD.

**Honest note:** no bot can guarantee a fixed accuracy percentage. This is a
disciplined, confluence-based framework with built-in stop-loss/take-profit
on every signal — always backtest and forward-test on a demo account before
using it with real money.

## 1. Get your keys

- **Telegram bot token:** message [@BotFather](https://t.me/BotFather) on
  Telegram → `/newbot` → copy the token it gives you.
- **TwelveData API key (free):** sign up at https://twelvedata.com →
  Dashboard → copy your API key. Free tier = 800 requests/day, 8/min, so
  don't poll forex pairs too aggressively.
- Binance needs no key for public market data (crypto).

## 2. Run locally (to test)

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and fill in your real keys, then:
export $(cat .env | xargs)   # loads the env vars (Linux/Mac)
python main.py
```

Open Telegram, find your bot, send `/start`.

## 3. Deploy on Railway

1. Push this folder to a GitHub repo.
2. On Railway: New Project → Deploy from GitHub repo.
3. In Railway's Variables tab, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TWELVEDATA_API_KEY`
4. Railway will detect `Procfile` and run `python main.py` as a worker.
5. Deploy — your bot stays online 24/7.

## 4. Usage

- `/start` — opens the Crypto / Forex menu with buttons.
- `/signal BTCUSDT` — direct signal for any Binance pair.
- `/signal EUR/USD` — direct signal for any forex/metal pair.

## 5. Files

| File | Purpose |
|---|---|
| `config.py` | Settings, pair lists, risk parameters |
| `data_fetcher.py` | Pulls candles from Binance / TwelveData |
| `indicators.py` | EMA, ATR, Fibonacci, BOS, FVG, volume logic |
| `strategy.py` | Combines everything into BUY/SELL/HOLD + SL/TP |
| `bot.py` | Telegram handlers and menus |
| `main.py` | Entry point |

## 6. Backtesting (do this before trusting any signal)

`backtest.py` replays the exact same strategy candle-by-candle on historical
data — no lookahead — and simulates each trade forward to see whether Stop
Loss or Take Profit was hit first. It reports win rate, profit factor,
average R, and max drawdown.

```bash
python backtest.py --symbol BTCUSDT --limit 1000
python backtest.py --symbol "EUR/USD" --limit 500
python backtest.py --symbol ETHUSDT --limit 1500 --max-hold 150 --csv trades.csv
```

- `--limit` — how many historical candles to pull (Binance allows up to
  1000 per request; for forex, mind TwelveData's free-tier daily quota).
- `--max-hold` — max candles a trade stays open before it's closed at
  market as a timeout (prevents trades hanging forever in quiet markets).
- `--csv` — optional path to save every simulated trade for your own review.

**Read the results honestly:** a profit factor > 1 with a reasonable win
rate over several hundred trades is a good sign, not a promise. Re-run it
on several different pairs and time ranges. If it loses money in backtest,
it will lose money live — tune `MIN_SCORE_FOR_SIGNAL`, `SL_ATR_MULTIPLIER`,
and `TP_ATR_MULTIPLIER` in `config.py` and re-test before going live.

## 7. Other next steps worth adding

- Add a `/watch SYMBOL` command that auto-alerts on every new candle close
  (needs a scheduler loop instead of only on-demand `/signal`).
- Forward-test on a demo account for a few weeks before using real money.
