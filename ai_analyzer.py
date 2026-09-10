import json
import requests
import asyncio
import config
import logging

logger = logging.getLogger(__name__)


def _fetch_gemini_response(url: str, payload: dict, headers: dict):
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        logger.error(f"Gemini API Error {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Gemini Request Failed: {e}")
    return None


async def analyze_market_with_ai(symbol: str, market_summary: dict) -> dict:
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY missing. Falling back to technical rules.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = f"""
    You are an elite Institutional SMC (Smart Money Concepts) Scalper.
    Analyze live market context for {symbol}:
    - Current Price: {market_summary.get('last_price')}
    - 15m HTF Trend: {market_summary.get('htf_bias')}
    - Candlestick Patterns: {market_summary.get('patterns')}
    - Volume Spike: {market_summary.get('volume_status')}
    - Recent Swing High: {market_summary.get('swing_high')}
    - Recent Swing Low: {market_summary.get('swing_low')}
    - ATR Volatility: {market_summary.get('atr')}
    - Golden Pocket Retracement: {market_summary.get('golden_pocket')}

    STRICT TRADING RULES FOR HIGH WIN-RATE:
    1. DEFAULT TO "HOLD" 80% OF THE TIME. Only give BUY or SELL if 15m Trend, Volume Spike, AND Patterns ALL align together.
    2. NEVER counter-trend trade against 15m HTF Trend.
    3. Stop Loss MUST be placed beyond the swing high/low with ATR breathing room.
    4. Provide confidence rating from 0 to 100. If confidence < 80, force signal to "HOLD".

    Return ONLY a raw JSON object with no markdown formatting:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number (0 to 100),
      "stop_loss": number,
      "take_profit": number,
      "reasons": ["Confluence 1", "Confluence 2"]
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
        
        # Force HOLD if AI confidence is below threshold
        min_conf = getattr(config, "MIN_AI_CONFIDENCE", 80)
        if parsed.get("confidence", 0) < min_conf:
            parsed["signal"] = "HOLD"
            parsed["reasons"] = [f"Confidence ({parsed.get('confidence')}%) below required {min_conf}% threshold for high accuracy."]

        return parsed
    except Exception as e:
        logger.error(f"AI Processing Exception for {symbol}: {e}")
        return None
