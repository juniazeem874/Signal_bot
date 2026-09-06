# Forex & Crypto Signal Bot

Telegram bot that gives BUY / SELL / HOLD signals for crypto (Binance) and
forex/metals (TwelveData) using a **multi-timeframe top-down strategy** —
the same general approach institutional/SMC traders use: higher timeframes
set the trend direction, the lowest timeframe times the entry.

**Timeframe stack:**
- **Crypto:** 4h → 1h → 15m → 5m → 1m (full stack, Binance has no meaningful rate limit)
- **Forex/metals:** 4h → 1h → 15m (stops there to protect TwelveData's free 800/day quota)

**How a signal fires:**
1. All higher timeframes must agree on direction (no dissenting timeframe) — otherwise it's HOLD, no matter what the lowest timeframe looks like.
2. On the entry timeframe (the last one in the stack), at least 2 of 3 checks must confirm: Break of Structure, FVG/Fibonacci 0.5-0.786 retracement zone, and a volume spike.
3. Every BUY/SELL comes with an ATR-based Stop Loss and Take Profit (per-asset multipliers in `config.py`).

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

## 3. Deploy on Render (free tier)

Render's free tier only supports **Web Services** (something listening on a
port) — Background Workers need a paid plan. So `main.py` runs a tiny Flask
health-check server alongside the real Telegram bot, which lets it run as a
free Web Service.

**Important limitation:** Render's free Web Services **sleep after 15
minutes with no HTTP traffic**, which would stop the bot's polling too. Fix
this with a free uptime pinger:

1. Push this folder to a GitHub repo (see the Git section below).
2. On Render: **New → Web Service** → connect your GitHub repo.
3. Render should auto-detect `render.yaml`. If not, set manually:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Plan:** Free
4. In the **Environment** tab, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TWELVEDATA_API_KEY`
5. Deploy. Once live, copy the `https://your-app.onrender.com` URL Render gives you.
6. Go to **uptimerobot.com** (free) → add a new monitor → paste that URL →
   set it to ping every 5 minutes. This stops Render from putting the
   service to sleep, so the bot keeps polling Telegram 24/7.

If you'd rather not deal with the sleep workaround, a paid Render
**Background Worker** ($7/month) runs `python main.py` directly without
needing Flask or a pinger at all.

## 4. Usage

- `/start` — opens the Crypto / Forex menu with buttons.
- `/signal BTCUSDT` — direct signal for any Binance pair.
- `/signal EUR/USD` — direct signal for any forex/metal pair.

## 5. Files

| File | Purpose |
|---|---|
| `config.py` | Settings, timeframe stacks, per-asset risk parameters |
| `data_fetcher.py` | Pulls candles from Binance / TwelveData (single or multi-timeframe) |
| `indicators.py` | EMA (incl. adaptive), ATR, Fibonacci, BOS, FVG, volume logic |
| `strategy.py` | Multi-timeframe top-down confluence engine (BUY/SELL/HOLD + SL/TP) |
| `bot.py` | Telegram handlers, menus, and `/backtest` |
| `main.py` | Entry point (+ health server for Render's free tier) |
| `backtest.py` | Multi-timeframe historical replay and trade simulation |

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
