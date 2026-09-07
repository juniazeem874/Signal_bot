import config
import indicators as ind
import ai_analyzer


def analyze(entry_df, trend_df, symbol="UNKNOWN"):
    entry_df = ind.add_atr(entry_df)
    entry_df = ind.add_volume_sma(entry_df, period=20)

    htf_bias = ind.get_htf_bias(trend_df)
    marubozu = ind.detect_marubozu(entry_df)
    engulfing = ind.detect_engulfing(entry_df)
    fakeout = ind.detect_fake_breakout(entry_df)
    rejection = ind.detect_rejection_candle(entry_df)
    fvg = ind.detect_fvg(entry_df)

    swing_high, swing_low = ind.find_last_swing(entry_df)
    last_price = entry_df.iloc[-1]["close"]

    in_gp_bull = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bullish")
    in_gp_bear = ind.is_in_golden_pocket(last_price, swing_high, swing_low, "bearish")
    has_volume_confirm = ind.has_above_avg_volume(entry_df, period=20)

    patterns = []
    if marubozu != "none": patterns.append(marubozu)
    if engulfing != "none": patterns.append(engulfing)
    if fakeout != "none": patterns.append(fakeout)
    if rejection != "none": patterns.append(rejection)
    if fvg != "none": patterns.append(fvg)

    market_summary = {
        "last_price": last_price,
        "htf_bias": htf_bias,
        "patterns": patterns if patterns else ["None"],
        "volume_status": "Above 20-SMA Spike" if has_volume_confirm else "Below Average / Low",
        "swing_high": swing_high,
        "swing_low": swing_low,
        "golden_pocket": "Bullish GP" if in_gp_bull else ("Bearish GP" if in_gp_bear else "None")
    }

    # ---- Try AI Analysis First ----
    ai_result = ai_analyzer.analyze_market_with_ai(symbol, market_summary)

    if ai_result and "signal" in ai_result:
        signal = ai_result.get("signal", "HOLD").upper()
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": signal,
            "confidence": ai_result.get("confidence", 70),
            "reasons": [f"[AI Insights] {r}" for r in ai_result.get("reasons", [])],
            "stop_loss": ai_result.get("stop_loss") if signal != "HOLD" else None,
            "take_profit": ai_result.get("take_profit") if signal != "HOLD" else None,
            "rr_ratio": config.MIN_RISK_REWARD,
        }

    # ---- Fallback Rule-Based Strategy ----
    bull_score = 0
    bear_score = 0
    bull_reasons, bear_reasons = [], []

    if htf_bias == "bullish": bull_score += 1; bull_reasons.append("15m HTF Trend is Bullish")
    if in_gp_bull: bull_score += 1; bull_reasons.append("Price in Golden Pocket Retracement")
    if engulfing == "bullish_engulfing" or marubozu == "bullish_marubozu":
        if has_volume_confirm:
            bull_score += 1.5
            bull_reasons.append("Bullish Momentum + 20-SMA Volume Spike")

    if htf_bias == "bearish": bear_score += 1; bear_reasons.append("15m HTF Trend is Bearish")
    if in_gp_bear: bear_score += 1; bear_reasons.append("Price in Golden Pocket Retracement")
    if engulfing == "bearish_engulfing" or marubozu == "bearish_marubozu":
        if has_volume_confirm:
            bear_score += 1.5
            bear_reasons.append("Bearish Momentum + 20-SMA Volume Spike")

    min_score = getattr(config, "MIN_SCORE_FOR_SIGNAL", 2)

    if bull_score >= min_score and bull_score > bear_score:
        sl = swing_low * (1.0 - config.SL_BUFFER_PERCENT)
        risk = last_price - sl
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": "BUY",
            "confidence": bull_score,
            "reasons": bull_reasons,
            "stop_loss": sl,
            "take_profit": last_price + (risk * config.MIN_RISK_REWARD),
            "rr_ratio": config.MIN_RISK_REWARD,
        }
    elif bear_score >= min_score and bear_score > bull_score:
        sl = swing_high * (1.0 + config.SL_BUFFER_PERCENT)
        risk = sl - last_price
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": "SELL",
            "confidence": bear_score,
            "reasons": bear_reasons,
            "stop_loss": sl,
            "take_profit": last_price - (risk * config.MIN_RISK_REWARD),
            "rr_ratio": config.MIN_RISK_REWARD,
        }

    return {
        "price": last_price,
        "trend_bias": htf_bias,
        "signal": "HOLD",
        "confidence": 0,
        "reasons": ["No momentum breakout aligned with AI or technical parameters."],
        "stop_loss": None,
        "take_profit": None,
        "rr_ratio": None,
    }
