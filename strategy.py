import config
import indicators as ind
import ai_analyzer
import news_fetcher


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

    # Fetch Fundamental / News Data
    news_data = news_fetcher.get_economic_news(symbol)

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
        "volume_status": "High Volume Spike (> 20 SMA)" if has_volume_confirm else "Normal Volume",
        "swing_high": swing_high,
        "swing_low": swing_low,
        "atr": latest_atr,
        "golden_pocket": "Bullish GP" if in_gp_bull else ("Bearish GP" if in_gp_bear else "None"),
        "news_data": news_data
    }

    # ---- AI Combined Fundamental + Technical Analysis ----
    ai_result = await ai_analyzer.analyze_market_with_ai(symbol, market_summary)

    if ai_result and "signal" in ai_result:
        signal = ai_result.get("signal", "HOLD").upper()
        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": signal,
            "confidence": ai_result.get("confidence", 85),
            "reasons": ai_result.get("reasons", ["Multi-factor analysis complete."]),
            "stop_loss": ai_result.get("stop_loss"),
            "take_profit": ai_result.get("take_profit"),
            "rr_ratio": getattr(config, "MIN_RISK_REWARD", 1.8),
        }

    # Fallback to HOLD if analysis incomplete
    return {
        "price": last_price,
        "trend_bias": htf_bias,
        "signal": "HOLD",
        "confidence": 0,
        "reasons": ["Awaiting strong technical + fundamental news confirmation."],
        "stop_loss": None,
        "take_profit": None,
        "rr_ratio": None,
    }
