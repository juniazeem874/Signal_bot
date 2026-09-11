import config
import indicators as ind
import ai_analyzer
import news_fetcher
import data_fetcher


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

    # Candle-close price from TwelveData/Yahoo free-tier feeds can lag the
    # real market by a few minutes — pull a live spot quote for metals so the
    # displayed price matches what you'd see on a broker/market chart.
    symbol_upper = symbol.upper()
    if symbol_upper in ("XAU/USD", "XAUUSD", "GOLD"):
        live_price = data_fetcher.fetch_goldapi_price("XAU")
        if live_price:
            last_price = live_price
    elif symbol_upper in ("XAG/USD", "XAGUSD", "SILVER"):
        live_price = data_fetcher.fetch_goldapi_price("XAG")
        if live_price:
            last_price = live_price

    exness_buffer = config.EXNESS_SPREAD_BUFFERS.get(symbol, 0.0002)

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
        "volume_status": "High Volume Surge (> 20 SMA)" if ind.has_above_avg_volume(entry_df, period=20) else "Normal",
        "swing_high": swing_high,
        "swing_low": swing_low,
        "atr": latest_atr,
        "exness_buffer": exness_buffer,
        "news_data": news_data
    }

    ai_result = await ai_analyzer.analyze_market_with_ai(symbol, market_summary)

    if ai_result and "signal" in ai_result:
        signal = ai_result.get("signal", "HOLD").upper()
        raw_sl = ai_result.get("stop_loss")
        raw_tp = ai_result.get("take_profit")

        # Adjust SL/TP with Exness Buffer Padding
        if signal == "BUY" and raw_sl:
            raw_sl -= exness_buffer
        elif signal == "SELL" and raw_sl:
            raw_sl += exness_buffer

        return {
            "price": last_price,
            "trend_bias": htf_bias,
            "signal": signal,
            "confidence": ai_result.get("confidence", 85),
            "reasons": ai_result.get("reasons", []),
            "stop_loss": raw_sl,
            "take_profit": raw_tp,
            "rr_ratio": getattr(config, "MIN_RISK_REWARD", 1.8),
            "market_summary": market_summary
        }

    return {
        "price": last_price,
        "trend_bias": htf_bias,
        "signal": "HOLD",
        "confidence": 0,
        "reasons": ["Awaiting high-probability Exness confluence setup."],
        "stop_loss": None,
        "take_profit": None,
        "rr_ratio": None,
        "market_summary": market_summary
    }
