"""
Updated strategy.py: Institutional Multi-Confluence Scalping Strategy.
Combines 15m HTF VWAP Trend Bias, 1m Fakeout (Bull/Bear Traps),
Pinbar Rejection Candles, Engulfing/FVG, Fibonacci Golden Pocket, and Volume Spikes.
"""

import config
import indicators as ind


def analyze(entry_df, trend_df):
    """
    entry_df  -> Lower Timeframe candles (1m LTF Execution)
    trend_df  -> Higher Timeframe candles (15m HTF Anchor)
    """
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_sma(entry_df)

    htf_bias = ind.get_htf_bias(trend_df)

    # Candle Pattern & Fakeout Detectors
    fvg = ind.detect_fvg(entry_df)
    engulfing = ind.detect_engulfing(entry_df)
    rejection_candle = ind.detect_rejection_candle(entry_df)
    fakeout = ind.detect_fake_breakout(entry_df)

    swing_high, swing_low = ind.find_last_swing(entry_df)
    last_price = entry_df.iloc[-1]["close"]

    in_gp_bull = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bullish")
    in_gp_bear = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bearish")

    # Volume spike check (includes Forex fallback when volume data is 0)
    vol_confirmed = ind.volume_spike_confirms(entry_df) or entry_df.iloc[-1]["volume"] == 0

    # ---- Score Bullish Case ----
    bull_score = 0
    bull_reasons = []

    if htf_bias == "bullish":
        bull_score += 1
        bull_reasons.append("15m HTF Trend is Bullish (Price > VWAP & EMA50 > EMA200)")

    if in_gp_bull:
        bull_score += 1
        bull_reasons.append("Price in Fibonacci Golden Pocket Retracement Zone (0.618 - 0.705)")

    if fakeout == "bullish_fakeout" or rejection_candle == "bullish_rejection" or engulfing == "bullish_engulfing" or fvg == "bullish_fvg":
        bull_score += 1
        patterns = []
        if fakeout == "bullish_fakeout": patterns.append("Bear Trap Fakeout (Liquidity Grab)")
        if rejection_candle == "bullish_rejection": patterns.append("Pinbar / Lower Wick Rejection")
        if engulfing == "bullish_engulfing": patterns.append("Bullish Engulfing Candle")
        if fvg == "bullish_fvg": patterns.append("Bullish FVG")
        bull_reasons.append(f"Candle Trigger: {', '.join(patterns)}")

    if vol_confirmed:
        bull_score += 1
        bull_reasons.append("Volume Spike Confirmed (>= 1.5x 5-period SMA)")

    # ---- Score Bearish Case ----
    bear_score = 0
    bear_reasons = []

    if htf_bias == "bearish":
        bear_score += 1
        bear_reasons.append("15m HTF Trend is Bearish (Price < VWAP & EMA50 < EMA200)")

    if in_gp_bear:
        bear_score += 1
        bear_reasons.append("Price in Fibonacci Golden Pocket Retracement Zone (0.618 - 0.705)")

    if fakeout == "bearish_fakeout" or rejection_candle == "bearish_rejection" or engulfing == "bearish_engulfing" or fvg == "bearish_fvg":
        bear_score += 1
        patterns = []
        if fakeout == "bearish_fakeout": patterns.append("Bull Trap Fakeout (Liquidity Grab)")
        if rejection_candle == "bearish_rejection": patterns.append("Pinbar / Upper Wick Rejection")
        if engulfing == "bearish_engulfing": patterns.append("Bearish Engulfing Candle")
        if fvg == "bearish_fvg": patterns.append("Bearish FVG")
        bear_reasons.append(f"Candle Trigger: {', '.join(patterns)}")

    if vol_confirmed:
        bear_score += 1
        bear_reasons.append("Volume Spike Confirmed (>= 1.5x 5-period SMA)")

    result = {
        "price": last_price,
        "trend_bias": htf_bias,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }

    min_score = getattr(config, "MIN_SCORE_FOR_SIGNAL", 2)

    # Signal Output Logic
    if bull_score >= min_score and bull_score > bear_score:
        sl = swing_low * (1.0 - config.SL_BUFFER_PERCENT)
        risk = last_price - sl
        tp = last_price + (risk * config.MIN_RISK_REWARD)

        result.update({
            "signal": "BUY",
            "confidence": bull_score,
            "reasons": bull_reasons,
            "stop_loss": sl,
            "take_profit": tp,
            "rr_ratio": config.MIN_RISK_REWARD,
        })
    elif bear_score >= min_score and bear_score > bull_score:
        sl = swing_high * (1.0 + config.SL_BUFFER_PERCENT)
        risk = sl - last_price
        tp = last_price - (risk * config.MIN_RISK_REWARD)

        result.update({
            "signal": "SELL",
            "confidence": bear_score,
            "reasons": bear_reasons,
            "stop_loss": sl,
            "take_profit": tp,
            "rr_ratio": config.MIN_RISK_REWARD,
        })
    else:
        result.update({
            "signal": "HOLD",
            "confidence": max(bull_score, bear_score),
            "reasons": ["No clear candle fakeout or trend confluence aligned yet."],
            "stop_loss": None,
            "take_profit": None,
            "rr_ratio": None,
        })

    return result
