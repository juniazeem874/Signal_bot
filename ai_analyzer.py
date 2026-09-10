import json
import requests
import asyncio
import config
import logging

logger = logging.getLogger(__name__)

def _fetch_gemini_response(url: str, payload: dict, headers: dict):
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        if response.status_code == 200:
            return response.json()
        logger.error(f"Gemini API Error {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Gemini Request Failed: {e}")
    return None

async def analyze_market_with_ai(symbol: str, market_summary: dict) -> dict:
    """Active Exness Scalper Prompt with Balanced Signal Frequency."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = f"""
    You are an Active Institutional Exness Scalper. Your job is to find active BUY or SELL scalping trades on 1m timeframe using 15m HTF alignment.

    --- MARKET DATA ---
    - Pair: {symbol}
    - Live Price: {market_summary.get('last_price')}
    - 15m HTF Trend: {market_summary.get('htf_bias')}
    - Price Patterns / Rejections: {market_summary.get('patterns')}
    - Swing High: {market_summary.get('swing_high')} | Swing Low: {market_summary.get('swing_low')}
    - ATR Volatility: {market_summary.get('atr')}
    - Exness Spread Buffer: {market_summary.get('exness_buffer')}

    --- NEWS / ECONOMIC CALENDAR ---
    - Currency: {market_summary.get('news_data', {}).get('currency')}
    - Status: {market_summary.get('news_data', {}).get('news_status')}
    - Upcoming High-Impact Events: {market_summary.get('news_data', {}).get('upcoming_events')}

    --- SCALPING EXECUTION RULES ---
    1. If 15m HTF Trend is BULLISH and 1m price is creating higher lows / rejection candles, generate "BUY".
    2. If 15m HTF Trend is BEARISH and 1m price is creating lower highs / rejection candles, generate "SELL".
    3. Do NOT stay in HOLD if there is a clear directional push or pattern alignment with 15m trend.
    4. If a high-impact news event is imminent for this pair's currency, lower confidence or prefer HOLD — news volatility can invalidate technical setups.
    5. Include Exness spread buffer ({market_summary.get('exness_buffer')}) in Stop Loss calculation.
    6. Set Confidence between 70% to 95% based on setup quality, adjusted down if high-impact news is pending.

    Return ONLY valid raw JSON format:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number,
      "stop_loss": number,
      "take_profit": number,
      "reasons": [
        "Core technical setup reason",
        "Exness execution & risk logic"
      ]
    }}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        res_data = await asyncio.to_thread(_fetch_gemini_response, url, payload, headers)
        if not res_data:
            return None

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text.replace("```", "").strip()

        parsed = json.loads(raw_text)
        min_conf = getattr(config, "MIN_AI_CONFIDENCE", 70)

        if parsed.get("confidence", 0) < min_conf:
            parsed["signal"] = "HOLD"
            parsed["reasons"] = [f"Confidence ({parsed.get('confidence')}%) below active threshold ({min_conf}%)."]

        return parsed
    except Exception as e:
        logger.error(f"AI Processing Exception for {symbol}: {e}")
        return None
