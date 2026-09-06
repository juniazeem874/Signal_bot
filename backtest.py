"""
Backtests the multi-timeframe strategy in strategy.py on historical candles.

Fetches each timeframe in the stack directly (not resampled), then walks
forward on the entry (lowest) timeframe candle-by-candle. At each step, every
higher timeframe is cut off at the current candle's timestamp so the
strategy only ever sees what would have been known at that moment (no
lookahead). Whenever it would have signaled BUY/SELL, the trade is
simulated forward to see whether Stop Loss or Take Profit was hit first.

Usage:
    python backtest.py --symbol BTCUSDT --limit 1000
    python backtest.py --symbol "EUR/USD" --limit 500
"""

import argparse
import pandas as pd
import numpy as np

import config
import data_fetcher as dfetch
import strategy

WARMUP_CANDLES = 40  # entry timeframe needs some history for ATR/swing/BOS lookback
MIN_HIGHER_TF_CANDLES = 5  # don't trust a higher timeframe bias off fewer than this


def simulate_trade(df: pd.DataFrame, entry_idx: int, result: dict, max_hold: int):
    """
    Walk forward from entry_idx+1 checking each candle's high/low against
    SL/TP. Conservative assumption: if a single candle touches both SL and
    TP, SL is assumed to hit first (worst case).
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

    exit_price = df.iloc[end_idx]["close"]
    if direction == "BUY":
        r = (exit_price - entry_price) / risk if risk > 0 else 0
    else:
        r = (entry_price - exit_price) / risk if risk > 0 else 0
    outcome = "win" if r > 0 else "loss"
    return {"outcome": outcome, "r_multiple": r, "exit_index": end_idx, "exit_reason": "timeout"}


def run_backtest(symbol: str, stack: list, limit: int, max_hold: int):
    entry_tf = stack[-1]
    higher_tfs = stack[:-1]

    print(f"Fetching multi-timeframe data for {symbol}: {stack}")
    dfs_full = {}
    dfs_full[entry_tf] = dfetch.fetch_candles(symbol, entry_tf, limit=limit).reset_index(drop=True)
    for tf in higher_tfs:
        # Higher timeframes get at least 250 candles regardless of --limit,
        # so EMA200-based bias has enough history even if --limit is small.
        dfs_full[tf] = dfetch.fetch_candles(symbol, tf, limit=max(limit, 250)).reset_index(drop=True)

    entry_full = dfs_full[entry_tf]
    if len(entry_full) < WARMUP_CANDLES + 20:
        raise ValueError(
            f"Not enough entry-timeframe candles ({len(entry_full)}) for a meaningful backtest. "
            f"Need at least {WARMUP_CANDLES + 20}."
        )

    higher_times = {tf: dfs_full[tf]["time"].values for tf in higher_tfs}

    trades = []
    i = WARMUP_CANDLES
    while i < len(entry_full) - 1:
        current_time = entry_full.iloc[i]["time"]

        dfs_slice = {entry_tf: entry_full.iloc[:i + 1]}
        enough_history = True
        for tf in higher_tfs:
            cutoff = np.searchsorted(higher_times[tf], np.datetime64(current_time), side="right")
            if cutoff < MIN_HIGHER_TF_CANDLES:
                enough_history = False
                break
            dfs_slice[tf] = dfs_full[tf].iloc[:cutoff]

        if not enough_history:
            i += 1
            continue

        result = strategy.analyze_mtf(dfs_slice, stack, symbol=symbol)

        if result["signal"] in ("BUY", "SELL"):
            trade = simulate_trade(entry_full, i, result, max_hold)
            trade["entry_index"] = i
            trade["entry_time"] = str(entry_full.iloc[i]["time"])
            trade["direction"] = result["signal"]
            trade["confidence"] = result["confidence"]
            trades.append(trade)
            i = trade["exit_index"] + 1  # one trade at a time, resume after it closes
        else:
            i += 1

    return trades


def build_report_text(trades, symbol) -> str:
    if not trades:
        return (
            f"No trades were triggered for {symbol} in this data range.\n"
            f"Try a longer limit, or a different pair/timeframe."
        )

    n = len(trades)
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    win_rate = len(wins) / n * 100

    gross_profit = sum(t["r_multiple"] for t in wins)
    gross_loss = abs(sum(t["r_multiple"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_r = sum(t["r_multiple"] for t in trades) / n

    equity = np.cumsum([t["r_multiple"] for t in trades])
    running_max = np.maximum.accumulate(equity)
    drawdown = running_max - equity
    max_dd = drawdown.max() if len(drawdown) else 0

    lines = [
        f"Backtest report: {symbol}",
        f"Total trades: {n}",
        f"Wins / Losses: {len(wins)} / {len(losses)}",
        f"Win rate: {win_rate:.1f}%",
        f"Profit factor: {profit_factor:.2f}",
        f"Avg R per trade: {avg_r:.2f}",
        f"Total R: {equity[-1]:.2f}",
        f"Max drawdown: {max_dd:.2f}R",
        "",
        "Note: fixed R risk-reward from config.py's ATR multipliers.",
        "Past performance does not guarantee future results.",
    ]
    return "\n".join(lines)


def print_report(trades, symbol):
    print("\n" + build_report_text(trades, symbol) + "\n")


def save_trades_csv(trades, path):
    if not trades:
        return
    pd.DataFrame(trades).to_csv(path, index=False)
    print(f"\nTrade log saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the multi-timeframe SMC+Fib+Volume strategy")
    parser.add_argument("--symbol", required=True, help="e.g. BTCUSDT or 'EUR/USD'")
    parser.add_argument("--limit", type=int, default=1000, help="number of entry-timeframe candles to fetch")
    parser.add_argument("--max-hold", type=int, default=100, help="max candles to hold a trade before timeout")
    parser.add_argument("--csv", default=None, help="optional path to save the trade log as CSV")
    args = parser.parse_args()

    is_forex = dfetch.is_forex_symbol(args.symbol)
    stack = config.MTF_STACK_FOREX if is_forex else config.MTF_STACK_CRYPTO

    trades = run_backtest(args.symbol, stack, args.limit, args.max_hold)
    print_report(trades, args.symbol)
    if args.csv:
        save_trades_csv(trades, args.csv)
