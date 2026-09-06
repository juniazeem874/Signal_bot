"""
Confluence-based strategy: combines trend (EMA), SMC (BOS + FVG), Fibonacci
retracement zone, and volume confirmation into a single BUY / SELL / HOLD
signal, with a transparent score and suggested SL/TP.

This is NOT a guaranteed-accuracy system - no such thing exists. It is a
disciplined, confluence-based framework: a signal only fires when multiple
independent conditions line up, and every signal comes with a stop-loss.
"""

import config
import indicators as ind


def analyze(entry_df, trend_df):
    """
    entry_df  -> lower timeframe candles (used for entry timing, Fib, FVG, volume)
    trend_df  -> higher timeframe candles (used for overall trend bias)

    Returns a dict describing the signal.
    """
    entry_df = ind.add_emas(entry_df)
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_avg(entry_df)

    trend_df = ind.add_emas(trend_df)

    trend_bias = ind.get_trend_bias(trend_df)          # bullish / bearish / neutral
    bos = ind.detect_bos(entry_df)                      # bullish_bos / bearish_bos / none
    fvg = ind.detect_fvg(entry_df)                       # bullish_fvg / bearish_fvg / none

    swing_high, swing_low = ind.find_last_swing(entry_df)
    fib = ind.fibonacci_levels(swing_high, swing_low)
    last_price = entry_df.iloc[-1]["close"]
    in_fib_zone = ind.price_in_fib_zone(last_price, fib)

    vol_confirms_bull = ind.volume_confirms(entry_df, "bullish")
    vol_confirms_bear = ind.volume_confirms(entry_df, "bearish")

    # ---- Score bullish case ----
    bull_score = 0
    bull_reasons = []
    if trend_bias == "bullish":
        bull_score += 1
        bull_reasons.append("Higher-timeframe trend is bullish (EMA50 > EMA200)")
    if bos == "bullish_bos":
        bull_score += 1
        bull_reasons.append("Bullish Break of Structure detected")
    if fvg == "bullish_fvg" or in_fib_zone:
        bull_score += 1
        bull_reasons.append("Price at bullish FVG / Fibonacci 0.5-0.786 retracement zone")
    if vol_confirms_bull:
        bull_score += 1
        bull_reasons.append("Volume spike confirms bullish move")

    # ---- Score bearish case ----
    bear_score = 0
    bear_reasons = []
    if trend_bias == "bearish":
        bear_score += 1
        bear_reasons.append("Higher-timeframe trend is bearish (EMA50 < EMA200)")
    if bos == "bearish_bos":
        bear_score += 1
        bear_reasons.append("Bearish Break of Structure detected")
    if fvg == "bearish_fvg" or in_fib_zone:
        bear_score += 1
        bear_reasons.append("Price at bearish FVG / Fibonacci 0.5-0.786 retracement zone")
    if vol_confirms_bear:
        bear_score += 1
        bear_reasons.append("Volume spike confirms bearish move")

    atr = entry_df.iloc[-1]["atr"]
    result = {
        "price": last_price,
        "trend_bias": trend_bias,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }

    if bull_score >= config.MIN_SCORE_FOR_SIGNAL and bull_score > bear_score:
        sl = last_price - atr * config.SL_ATR_MULTIPLIER
        tp = last_price + atr * config.TP_ATR_MULTIPLIER
        result.update({
            "signal": "BUY",
            "confidence": bull_score,
            "reasons": bull_reasons,
            "stop_loss": sl,
            "take_profit": tp,
        })
    elif bear_score >= config.MIN_SCORE_FOR_SIGNAL and bear_score > bull_score:
        sl = last_price + atr * config.SL_ATR_MULTIPLIER
        tp = last_price - atr * config.TP_ATR_MULTIPLIER
        result.update({
            "signal": "SELL",
            "confidence": bear_score,
            "reasons": bear_reasons,
            "stop_loss": sl,
            "take_profit": tp,
        })
    else:
        result.update({
            "signal": "HOLD",
            "confidence": max(bull_score, bear_score),
            "reasons": ["No strong confluence yet — conditions not aligned for an entry"],
            "stop_loss": None,
            "take_profit": None,
        })

    return result
