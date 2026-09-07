import json
import requests
import asyncio
import config
import logging

logger = logging.getLogger(__name__)


def _fetch_gemini_response(url: str, payload: dict, headers: dict):
    """Internal synchronous function executed in background thread."""
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=8)
        if response.status_code == 200:
            return response.json()
        logger.error(f"Gemini API Error {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Gemini Request Failed: {e}")
    return None


async def analyze_market_with_ai(symbol: str, market_summary: dict) -> dict:
    """Async AI analyzer with strict timeout protection."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY missing. Falling back to technical indicators.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = f"""
    You are an expert Institutional Trader. Analyze this market context for {symbol}:
    - Current Price: {market_summary.get('last_price')}
    - HTF Trend (15m): {market_summary.get('htf_bias')}
    - Patterns: {market_summary.get('patterns')}
    - Volume: {market_summary.get('volume_status')}
    - Golden Pocket: {market_summary.get('golden_pocket')}

    Return ONLY a raw JSON object with no markdown formatting:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number,
      "stop_loss": number,
      "take_profit": number,
      "reasons": ["reason 1", "reason 2"]
    }}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        # Run synchronous requests in a thread to keep Telegram bot responsive
        res_data = await asyncio.to_thread(_fetch_gemini_response, url, payload, headers)
        if not res_data:
            return None

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text.replace("```", "").strip()

        return json.loads(raw_text)
    except Exception as e:
        logger.error(f"AI Processing Exception for {symbol}: {e}")
        return None
