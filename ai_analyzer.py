import json
import requests
import config
import logging

logger = logging.getLogger(__name__)


def analyze_market_with_ai(symbol: str, market_summary: dict) -> dict:
    """Sends structured technical market data to Gemini AI for deep analysis."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not found. Skipping AI analysis.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = f"""
    You are an expert Institutional Price Action & Scalping Trader using Marubozu Momentum, Engulfing, Volume 20-SMA Filters, and Fakeout Traps.

    Analyze the following live market data for symbol: {symbol}

    Market Summary:
    - Current Price: {market_summary.get('last_price')}
    - 15m HTF Trend Bias: {market_summary.get('htf_bias')}
    - Candlestick Patterns Detected: {market_summary.get('patterns')}
    - Volume Status (20-SMA Filter): {market_summary.get('volume_status')}
    - Recent Swing High: {market_summary.get('swing_high')}
    - Recent Swing Low: {market_summary.get('swing_low')}
    - Golden Pocket Retracement: {market_summary.get('golden_pocket')}

    Provide a trading decision in strict JSON format only without markdown block formatting:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number (between 0 and 100),
      "stop_loss": number,
      "take_profit": number,
      "reasons": ["reason 1", "reason 2", "reason 3"]
    }}

    Rules:
    1. If market lacks high momentum, volume spike, or clean structure, set signal to "HOLD".
    2. Maintain at least 1:2 Risk-to-Reward ratio for BUY/SELL signals.
    3. Output valid JSON only.
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        if response.status_code == 200:
            res_data = response.json()
            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            # Clean Markdown wrappers if present
            if raw_text.startswith("```json"):
                raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.replace("```", "").strip()

            parsed = json.loads(raw_text)
            return parsed
        else:
            logger.error(f"Gemini API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logger.error(f"AI Analysis Failed: {e}")
        return None
