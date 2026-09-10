import config
import indicators as ind
import ai_analyzer


async def analyze(entry_df, trend_df, symbol="UNKNOWN"):
    entry_df = ind.add_atr(entry_df, period=getattr(config, "ATR_PERIOD", 14))
    entry_df = ind.add_volume_sma(entry_df, period=20)

    htf_bias = ind.get_htf_bias(trend_df)
    marubozu = ind.detect_marubozu(entry_df)
    engulfing = ind.detect_engulfing(entry_df)
    fakeout = ind.detect_fake_breakout(entry_df)
    rejection = ind.detect_rejection_candle(entry_df)
    fvg = ind.detect_fvg(entry_df)

    swing_high, swing_low = ind.find_last_swing(entry_df)
    last_price = entry_df.iloc[-1]["close"]
    latest_atr = entry_df.iloc[-1]["atr"] if "atr" in entry_df.columns else (last_price * 0.001)

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
        "volume_status": "High Volume Spike (> 20 SMA)" if has_volume_confirm else "Below Average",
        "swing_high": swing_high,
        "swing_low": swing_low,
        "atr": latest_atr,
        "golden_pocket": "Bullish GP" if in_gp_bull else ("Bearish GP" if in_gp_bear else "None")
    }

    # ---- 1. AI Analysis Call ----
    ai_result = await ai_analyzer.analyze_market_with_ai(symbol, market_summary)

    if ai_result and "signal" in ai_result:
        signal = ai_result.get("signal", "HOLD").upper()
        if signal in ["BUY", "SELL"]:
            return {
                "price": last_price,
                "trend_bias": htf_bias,
                "signal": signal,
                "confidence": ai_result.get("confidence", 80),
                "reasons": [f"🤖 {r}" for r in ai_result.get("reasons", [])],
                "stop_loss": ai_result.get("stop_loss"),
                "take_profit": ai_result.get("take_profit"),
                "rr_ratio": getattr(config, "MIN_RISK_REWARD", 1.8),
            }

    # ---- 2. Fallback Technical Rule-Based Strategy ----
    bull_score = 0
    bear_score = 0
    bull_reasons, bear_reasons = [], []
    atr_mult = getattr(config, "ATR_SL_MULTIPLIER", 1.5)
    rr = getattr(config, "MIN_RISK_REWARD", 1.8)

    if htf_bias == "bullish": bull_score += 1; bull_reasons.append("15m HTF Bullish Structure")
    if in_gp_bull: bull_score += 1; bull_reasons.append("Golden Pocket Support Level")
    if engulfing == "bullish_engulfing" or marubozu == "bullish_marubozu":
        if has_volume_confirm:
            bull_score += 1.5
            bull_reasons.append("High-Volume Bullish Expansion")

    if htf_bias == "bearish": bear_score += 1; bear_reasons.append("15m HTF Bearish Structure")
    if in_gp_bear: bear_score += 1; bear_reasons.append("Golden Pocket Resistance Level")
    if engulfing == "bearish_engulfing" or marubozu == "bearish_marubozu":
        if has_volume_confirm:
            bear_score += 1.5
            bear_reasons.append("High-Volume Bearish Expansion")

    if bull_score >= 2.5 and bull_score > bear_score:
        sl = swing_low - (latest_atr * atr_mult)
        risk = last_price - sl
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": "BUY",
            "confidence": bull_score,
            "reasons": bull_reasons,
            "stop_loss": sl,
            "take_profit": last_price + (risk * rr),
            "rr_ratio": rr,
        }
    elif bear_score >= 2.5 and bear_score > bull_score:
        sl = swing_high + (latest_atr * atr_mult)
        risk = sl - last_price
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": "SELL",
            "confidence": bear_score,
            "reasons": bear_reasons,
            "stop_loss": sl,
            "take_profit": last_price - (risk * rr),
            "rr_ratio": rr,
        }

    return {
        "price": last_price,
        "trend_bias": htf_bias,
        "signal": "HOLD",
        "confidence": 0,
        "reasons": ["Market lacks high-confluence institutional setup. Holding."],
        "stop_loss": None,
        "take_profit": None,
        "rr_ratio": None,
    }
