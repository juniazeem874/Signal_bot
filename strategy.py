"""
Institutional Multi-Confluence Scalping Strategy (PDF Implementation):
- Timeframes: 15m HTF Anchor + 1m LTF Execution
- HTF Bias: VWAP + Market Structure Shift (BOS)
- Fibonacci Matrix: 0.618 - 0.705 Golden Pocket
- LTF Catalyst: Engulfing / FVG / Liquidity Sweep
- Volume Trigger: >= 1.5x 5-period Volume SMA
- Execution: 1:2.5 Risk-to-Reward Ratio
"""

import config
import indicators as ind


def analyze(entry_df, trend_df):
    """
    entry_df  -> 1m candles (LTF Execution)
    trend_df  -> 15m candles (HTF Anchor)
    """
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_sma(entry_df)

    htf_bias = ind.get_htf_bias(trend_df)
    bos = ind.detect_bos(entry_df)
    fvg = ind.detect_fvg(entry_df)
    engulfing = ind.detect_engulfing(entry_df)
    sweep = ind.detect_liquidity_sweep(entry_df)

    swing_high, swing_low = ind.find_last_swing(entry_df)
    last_price = entry_df.iloc[-1]["close"]

    in_gp_bull = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bullish")
    in_gp_bear = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bearish")

    vol_confirmed = ind.volume_spike_confirms(entry_df)

    # ---- Score Bullish Case ----
    bull_score = 0
    bull_reasons = []

    if htf_bias == "bullish":
        bull_score += 1
        bull_reasons.append("15m HTF Bias is Bullish (Price above VWAP & EMA50 > EMA200)")

    if in_gp_bull:
        bull_score += 1
        bull_reasons.append("Price inside 15m/1m Fibonacci Golden Pocket (0.618 - 0.705)")

    if engulfing == "bullish_engulfing" or fvg == "bullish_fvg" or sweep == "bullish_sweep":
        bull_score += 1
        catalysts = []
        if engulfing == "bullish_engulfing": catalysts.append("Bullish Engulfing")
        if fvg == "bullish_fvg": catalysts.append("Bullish FVG")
        if sweep == "bullish_sweep": catalysts.append("Liquidity Sweep")
        bull_reasons.append(f"1m Catalyst Triggered: {', '.join(catalysts)}")

    if vol_confirmed:
        bull_score += 1
        bull_reasons.append("Volume Spike >= 1.5x 5-period SMA on trigger candle")

    # ---- Score Bearish Case ----
    bear_score = 0
    bear_reasons = []

    if htf_bias == "bearish":
        bear_score += 1
        bear_reasons.append("15m HTF Bias is Bearish (Price below VWAP & EMA50 < EMA200)")

    if in_gp_bear:
        bear_score += 1
        bear_reasons.append("Price inside 15m/1m Fibonacci Golden Pocket (0.618 - 0.705)")

    if engulfing == "bearish_engulfing" or fvg == "bearish_fvg" or sweep == "bearish_sweep":
        bear_score += 1
        catalysts = []
        if engulfing == "bearish_engulfing": catalysts.append("Bearish Engulfing")
        if fvg == "bearish_fvg": catalysts.append("Bearish FVG")
        if sweep == "bearish_sweep": catalysts.append("Liquidity Sweep")
        bear_reasons.append(f"1m Catalyst Triggered: {', '.join(catalysts)}")

    if vol_confirmed:
        bear_score += 1
        bear_reasons.append("Volume Spike >= 1.5x 5-period SMA on trigger candle")

    result = {
        "price": last_price,
        "trend_bias": htf_bias,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }

    # Stop Loss & Take Profit Calculation
    if bull_score >= config.MIN_SCORE_FOR_SIGNAL and bull_score > bear_score:
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
    elif bear_score >= config.MIN_SCORE_FOR_SIGNAL and bear_score > bull_score:
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
            "reasons": ["Institutional confluence incomplete — conditions not fully aligned."],
            "stop_loss": None,
            "take_profit": None,
            "rr_ratio": None,
        })

    return result
