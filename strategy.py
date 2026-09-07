"""
Scalping Strategy integrated with PDF Guide Rules:
- High Momentum (Marubozu)
- Volume 20-SMA Confirmation Filter
- Engulfing & Trap (Fakeout) Confirmations
"""

import config
import indicators as ind


def analyze(entry_df, trend_df):
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_sma(entry_df, period=20)

    htf_bias = ind.get_htf_bias(trend_df)

    marubozu = ind.detect_marubozu(entry_df)
    engulfing = ind.detect_engulfing(entry_df)
    fakeout = ind.detect_fake_breakout(entry_df)
    rejection_candle = ind.detect_rejection_candle(entry_df)
    fvg = ind.detect_fvg(entry_df)

    swing_high, swing_low = ind.find_last_swing(entry_df)
    last_price = entry_df.iloc[-1]["close"]

    in_gp_bull = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bullish")
    in_gp_bear = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bearish")

    # PDF Volume Filter Rule: Above-Average 20-SMA Volume Spikes
    has_volume_confirm = ind.has_above_avg_volume(entry_df, period=20)

    # ---- Bullish Logic ----
    bull_score = 0
    bull_reasons = []

    if htf_bias == "bullish":
        bull_score += 1
        bull_reasons.append("15m HTF Trend is Bullish")

    if in_gp_bull:
        bull_score += 1
        bull_reasons.append("Price in Golden Pocket Retracement")

    if (engulfing == "bullish_engulfing" or marubozu == "bullish_marubozu" or 
        fakeout == "bullish_fakeout" or rejection_candle == "bullish_rejection" or fvg == "bullish_fvg"):
        
        # Fakeouts fade low volume, Marubozu/Engulfing need high volume (PDF Rules)
        if fakeout == "bullish_fakeout":
            bull_score += 2
            bull_reasons.append("Bear Trap Fakeout (Liquidity Grab)")
        elif has_volume_confirm:
            bull_score += 1.5
            p_name = "Bullish Engulfing" if engulfing == "bullish_engulfing" else ("Marubozu Momentum" if marubozu == "bullish_marubozu" else "Pinbar/FVG")
            bull_reasons.append(f"Institutional Signal: {p_name} + Above-Avg Vol (20 SMA)")

    # ---- Bearish Logic ----
    bear_score = 0
    bear_reasons = []

    if htf_bias == "bearish":
        bear_score += 1
        bear_reasons.append("15m HTF Trend is Bearish")

    if in_gp_bear:
        bear_score += 1
        bear_reasons.append("Price in Golden Pocket Retracement")

    if (engulfing == "bearish_engulfing" or marubozu == "bearish_marubozu" or 
        fakeout == "bearish_fakeout" or rejection_candle == "bearish_rejection" or fvg == "bearish_fvg"):
        
        if fakeout == "bearish_fakeout":
            bear_score += 2
            bear_reasons.append("Bull Trap Fakeout (Liquidity Grab)")
        elif has_volume_confirm:
            bear_score += 1.5
            p_name = "Bearish Engulfing" if engulfing == "bearish_engulfing" else ("Marubozu Momentum" if marubozu == "bearish_marubozu" else "Pinbar/FVG")
            bear_reasons.append(f"Institutional Signal: {p_name} + Above-Avg Vol (20 SMA)")

    last_candle_vol = entry_df.iloc[-1]["volume"]
    if has_volume_confirm or last_candle_vol == 0:
        bull_score += 0.5
        bear_score += 0.5

    result = {
        "price": last_price,
        "trend_bias": htf_bias,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "swing_high": swing_high,
        "swing_low": swing_low,
    }

    min_score = getattr(config, "MIN_SCORE_FOR_SIGNAL", 2)

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
            "reasons": ["No momentum/engulfing breakout or trap setup aligned with 20-SMA volume."],
            "stop_loss": None,
            "take_profit": None,
            "rr_ratio": None,
        })

    return result
