"""
Multi-timeframe top-down strategy (the way institutional/SMC traders
actually work): higher timeframes set the trend direction, and the lowest
(entry) timeframe times the trigger using SMC (Break of Structure + Fair
Value Gap), Fibonacci retracement zone, and volume confirmation.

No accuracy number is baked in here or anywhere else - there is no such
thing as a guaranteed win rate. Run backtest.py / the /backtest command to
see what this actually does on real historical data before trusting it.
"""

import math

import config
import indicators as ind


def get_multi_tf_bias(dfs_by_tf: dict, higher_tfs: list) -> tuple:
    """
    Computes the trend bias on each higher timeframe and combines them into
    one overall direction. Requires NO dissenting timeframe (no bearish
    frame if calling it bullish, and vice versa) plus at least half the
    frames actively agreeing - anything messier is called 'neutral' (no
    trade), since the whole point of multi-timeframe analysis is that the
    frames should agree, not just outvote each other.

    Returns (overall_bias, {timeframe: bias}) for transparency in the
    signal message.
    """
    biases = {}
    for tf in higher_tfs:
        d = ind.add_adaptive_emas(dfs_by_tf[tf])
        biases[tf] = ind.get_trend_bias(d)

    n = len(biases)
    bull = sum(1 for b in biases.values() if b == "bullish")
    bear = sum(1 for b in biases.values() if b == "bearish")
    need = math.ceil(n / 2)

    if bear == 0 and bull >= need:
        overall = "bullish"
    elif bull == 0 and bear >= need:
        overall = "bearish"
    else:
        overall = "neutral"

    return overall, biases


def analyze_mtf(dfs_by_tf: dict, timeframe_stack: list, symbol=None) -> dict:
    """
    dfs_by_tf        -> {timeframe: candles_dataframe}, one entry per
                         timeframe in timeframe_stack
    timeframe_stack  -> ordered HTF -> LTF, e.g. ['4h','1h','15m','5m','1m'].
                         The LAST one is the entry/trigger timeframe.
    symbol           -> optional, used to look up per-asset SL/TP ATR multipliers

    Returns a dict describing the signal.
    """
    entry_tf = timeframe_stack[-1]
    higher_tfs = timeframe_stack[:-1]

    overall_bias, tf_biases = get_multi_tf_bias(dfs_by_tf, higher_tfs)

    entry_df = dfs_by_tf[entry_tf].copy()
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_avg(entry_df)

    bos = ind.detect_bos(entry_df)
    fvg = ind.detect_fvg(entry_df)
    swing_high, swing_low = ind.find_last_swing(entry_df)
    fib = ind.fibonacci_levels(swing_high, swing_low)
    last_price = entry_df.iloc[-1]["close"]
    in_fib_zone = ind.price_in_fib_zone(last_price, fib)
    vol_confirms_bull = ind.volume_confirms(entry_df, "bullish")
    vol_confirms_bear = ind.volume_confirms(entry_df, "bearish")

    entry_score = 0
    entry_reasons = [f"Higher-timeframe stack ({', '.join(higher_tfs)}) bias: {overall_bias}"]

    if overall_bias == "bullish":
        if bos == "bullish_bos":
            entry_score += 1
            entry_reasons.append(f"Bullish Break of Structure on {entry_tf}")
        if fvg == "bullish_fvg" or in_fib_zone:
            entry_score += 1
            entry_reasons.append(f"Bullish FVG / Fibonacci 0.5-0.786 zone on {entry_tf}")
        if vol_confirms_bull:
            entry_score += 1
            entry_reasons.append(f"Volume spike confirms bullish move on {entry_tf}")

    elif overall_bias == "bearish":
        if bos == "bearish_bos":
            entry_score += 1
            entry_reasons.append(f"Bearish Break of Structure on {entry_tf}")
        if fvg == "bearish_fvg" or in_fib_zone:
            entry_score += 1
            entry_reasons.append(f"Bearish FVG / Fibonacci 0.5-0.786 zone on {entry_tf}")
        if vol_confirms_bear:
            entry_score += 1
            entry_reasons.append(f"Volume spike confirms bearish move on {entry_tf}")

    atr = entry_df.iloc[-1]["atr"]
    sl_mult, tp_mult = config.get_risk_params(symbol)

    result = {
        "price": last_price,
        "overall_bias": overall_bias,
        "tf_biases": tf_biases,
        "entry_timeframe": entry_tf,
        "entry_score": entry_score,
    }

    if overall_bias in ("bullish", "bearish") and entry_score >= config.MTF_MIN_ENTRY_SCORE:
        if overall_bias == "bullish":
            sl = last_price - atr * sl_mult
            tp = last_price + atr * tp_mult
            signal = "BUY"
        else:
            sl = last_price + atr * sl_mult
            tp = last_price - atr * tp_mult
            signal = "SELL"
        result.update({
            "signal": signal,
            "confidence": entry_score,
            "reasons": entry_reasons,
            "stop_loss": sl,
            "take_profit": tp,
        })
    else:
        if overall_bias == "neutral":
            reasons = entry_reasons + ["Higher timeframes are not aligned — no trade"]
        else:
            reasons = entry_reasons + [f"Only {entry_score}/3 entry checks matched on {entry_tf}"]
        result.update({
            "signal": "HOLD",
            "confidence": entry_score,
            "reasons": reasons,
            "stop_loss": None,
            "take_profit": None,
        })

    return result
