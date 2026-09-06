"""
Backtests the strategy in strategy.py on historical candles.

Walks forward candle-by-candle (no lookahead), fires a simulated trade
whenever the strategy would have signaled BUY/SELL, then checks forward
candles to see whether Stop Loss or Take Profit was hit first. Reports
win rate, profit factor, average R, and max drawdown.

Usage:
    python backtest.py --symbol BTCUSDT --limit 1000
    python backtest.py --symbol "EUR/USD" --entry-interval 1h --limit 500
"""

import argparse
import pandas as pd
import numpy as np

import config
import data_fetcher as dfetch
import strategy

WARMUP_CANDLES = 210  # need enough history for EMA200 + swing lookback before trusting a signal

INTERVAL_TO_PANDAS_RULE = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
}


def resample_ohlcv(df: pd.DataFrame, target_interval: str) -> pd.DataFrame:
    """Resample a lower-timeframe OHLCV dataframe up to a higher timeframe."""
    rule = INTERVAL_TO_PANDAS_RULE.get(target_interval, target_interval)
    resampled = (
        df.set_index("time")
        .resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )
    return resampled


def simulate_trade(df: pd.DataFrame, entry_idx: int, result: dict, max_hold: int):
    """
    Walk forward from entry_idx+1 checking each candle's high/low against
    SL/TP. Conservative assumption: if a single candle touches both SL and
    TP, SL is assumed to hit first (worst case).
    Returns a dict describing the trade outcome, including the index where
    it closed (so the caller can resume scanning after it).
    """
    direction = result["signal"]
    entry_price = result["price"]
    sl = result["stop_loss"]
    tp = result["take_profit"]
    risk = abs(entry_price - sl)

    end_idx = min(entry_idx + max_hold, len(df) - 1)

    for j in range(entry_idx + 1, end_idx + 1):
        candle = df.iloc[j]
        if direction == "BUY":
            if candle["low"] <= sl:
                return {"outcome": "loss", "r_multiple": -1.0, "exit_index": j, "exit_reason": "SL"}
            if candle["high"] >= tp:
                r = (tp - entry_price) / risk if risk > 0 else 0
                return {"outcome": "win", "r_multiple": r, "exit_index": j, "exit_reason": "TP"}
        else:  # SELL
            if candle["high"] >= sl:
                return {"outcome": "loss", "r_multiple": -1.0, "exit_index": j, "exit_reason": "SL"}
            if candle["low"] <= tp:
                r = (entry_price - tp) / risk if risk > 0 else 0
                return {"outcome": "win", "r_multiple": r, "exit_index": j, "exit_reason": "TP"}

    # Neither hit within max_hold candles -> close at last available price (timeout)
    exit_price = df.iloc[end_idx]["close"]
    if direction == "BUY":
        r = (exit_price - entry_price) / risk if risk > 0 else 0
    else:
        r = (entry_price - exit_price) / risk if risk > 0 else 0
    outcome = "win" if r > 0 else "loss"
    return {"outcome": outcome, "r_multiple": r, "exit_index": end_idx, "exit_reason": "timeout"}


def run_backtest(symbol: str, entry_interval: str, trend_interval: str, limit: int, max_hold: int):
    print(f"Fetching {limit} candles for {symbol} ({entry_interval})...")
    df = dfetch.fetch_candles(symbol, entry_interval, limit=limit)
    df = df.reset_index(drop=True)

    if len(df) < WARMUP_CANDLES + 20:
        raise ValueError(
            f"Not enough candles ({len(df)}) for a meaningful backtest. "
            f"Need at least {WARMUP_CANDLES + 20}. Try a smaller timeframe or larger --limit."
        )

    trend_full = resample_ohlcv(df, trend_interval)
    trend_times = trend_full["time"].values

    trades = []
    i = WARMUP_CANDLES
    while i < len(df) - 1:
        current_time = df.iloc[i]["time"]
        cutoff = np.searchsorted(trend_times, np.datetime64(current_time), side="right")
        trend_slice = trend_full.iloc[:cutoff]

        if len(trend_slice) < 5:
            i += 1
            continue

        entry_slice = df.iloc[:i + 1]
        result = strategy.analyze(entry_slice.copy(), trend_slice.copy())

        if result["signal"] in ("BUY", "SELL"):
            trade = simulate_trade(df, i, result, max_hold)
            trade["entry_index"] = i
            trade["entry_time"] = str(df.iloc[i]["time"])
            trade["direction"] = result["signal"]
            trade["confidence"] = result["confidence"]
            trades.append(trade)
            i = trade["exit_index"] + 1  # one trade at a time, resume after it closes
        else:
            i += 1

    return trades


def print_report(trades, symbol):
    if not trades:
        print(f"\nNo trades were triggered for {symbol} in this data range.")
        print("Try a longer --limit, or a different pair/timeframe.")
        return

    n = len(trades)
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    win_rate = len(wins) / n * 100

    gross_profit = sum(t["r_multiple"] for t in wins)
    gross_loss = abs(sum(t["r_multiple"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_r = sum(t["r_multiple"] for t in trades) / n

    # Equity curve in R-multiples, for max drawdown
    equity = np.cumsum([t["r_multiple"] for t in trades])
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity
    max_dd = drawdown.max() if len(drawdown) else 0

    print(f"\n===== Backtest report: {symbol} =====")
    print(f"Total trades:     {n}")
    print(f"Wins / Losses:    {len(wins)} / {len(losses)}")
    print(f"Win rate:         {win_rate:.1f}%")
    print(f"Profit factor:    {profit_factor:.2f}")
    print(f"Avg R per trade:  {avg_r:.2f}")
    print(f"Total R:          {equity[-1]:.2f}")
    print(f"Max drawdown:     {max_dd:.2f}R")
    print("=======================================")
    print("Note: this uses fixed R risk-reward from config.py's ATR multipliers.")
    print("Past performance on historical data does not guarantee future results.")


def save_trades_csv(trades, path):
    if not trades:
        return
    pd.DataFrame(trades).to_csv(path, index=False)
    print(f"\nTrade log saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the SMC+Fib+Volume strategy")
    parser.add_argument("--symbol", required=True, help="e.g. BTCUSDT or 'EUR/USD'")
    parser.add_argument("--entry-interval", default=None, help="e.g. 1h (defaults per market type)")
    parser.add_argument("--trend-interval", default=None, help="e.g. 4h (defaults per market type)")
    parser.add_argument("--limit", type=int, default=1000, help="number of historical candles to fetch")
    parser.add_argument("--max-hold", type=int, default=100, help="max candles to hold a trade before timeout")
    parser.add_argument("--csv", default=None, help="optional path to save the trade log as CSV")
    args = parser.parse_args()

    is_forex = dfetch.is_forex_symbol(args.symbol)
    entry_interval = args.entry_interval or (
        config.ENTRY_INTERVAL_TWELVEDATA if is_forex else config.ENTRY_INTERVAL_BINANCE
    )
    trend_interval = args.trend_interval or (
        config.TREND_INTERVAL_TWELVEDATA if is_forex else config.TREND_INTERVAL_BINANCE
    )

    trades = run_backtest(args.symbol, entry_interval, trend_interval, args.limit, args.max_hold)
    print_report(trades, args.symbol)
    if args.csv:
        save_trades_csv(trades, args.csv)
