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
    """Institutional Exness Scalper Prompt - Deep Thinking & Setup Reasons."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    prompt = f"""
    You are an Institutional AI Scalper specialized in EXNESS broker execution (1m entry / 15m trend).
    Analyze live market setup for: {symbol}

    --- TECHNICAL DATA ---
    - Current Live Price: {market_summary.get('last_price')}
    - 15m HTF Trend Bias: {market_summary.get('htf_bias')}
    - Candlestick / SMC Patterns: {market_summary.get('patterns')}
    - Volume Spike Status: {market_summary.get('volume_status')}
    - Swing High: {market_summary.get('swing_high')} | Swing Low: {market_summary.get('swing_low')}
    - ATR Volatility: {market_summary.get('atr')}
    - Exness Spread Buffer: {market_summary.get('exness_buffer')}

    --- FUNDAMENTAL / NEWS CONTEXT ---
    - Currency: {market_summary.get('news_data', {}).get('currency')}
    - News Status: {market_summary.get('news_data', {}).get('news_status')}

    --- EXNESS TRADING RULES ---
    1. If High-Impact news is due within 30 minutes, signal MUST be "HOLD".
    2. Require strict SMC confluence (15m Trend Alignment + Volume Spike + Clear Liquidity Sweep/FVG/Pattern).
    3. Calculate Stop Loss & Take Profit with Exness spread buffer included ({market_summary.get('exness_buffer')}).
    4. Provide explicit step-by-step reasoning explaining WHY this trade is taken or why we are holding.
    5. Require minimum 85% confidence for BUY/SELL.

    Return ONLY valid JSON format:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number,
      "stop_loss": number,
      "take_profit": number,
      "reasons": [
        "Primary Technical Reason (e.g. 15m Trend + FVG Sweep)",
        "Secondary Reason (e.g. Exness Spread Buffer & Volume Surge)",
        "Risk Assessment"
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
        min_conf = getattr(config, "MIN_AI_CONFIDENCE", 85)

        if parsed.get("confidence", 0) < min_conf:
            parsed["signal"] = "HOLD"
            parsed["reasons"] = [f"Confidence ({parsed.get('confidence')}%) is below strict Exness threshold ({min_conf}%)."]

        return parsed
    except Exception as e:
        logger.error(f"AI Processing Exception for {symbol}: {e}")
        return None


async def check_active_trade_reversal(symbol: str, active_trade: dict, market_summary: dict) -> dict:
    """Evaluates if an OPEN trade should be CLOSED IMMEDIATELY due to trend reversal."""
    api_key = getattr(config, "GEMINI_API_KEY", "")
    if not api_key:
        return {"action": "HOLD", "reason": "No AI key"}

    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=){api_key}"

    trade_type = active_trade.get("signal")  # BUY or SELL
    entry_price = active_trade.get("price")

    prompt = f"""
    You are an Exness Active Risk Management AI.
    We currently have an ACTIVE {trade_type} trade open on {symbol}.

    --- ACTIVE TRADE DETAILS ---
    - Type: {trade_type}
    - Entry Price: {entry_price}
    - Current SL: {active_trade.get('stop_loss')}
    - Current TP: {active_trade.get('take_profit')}

    --- CURRENT LIVE MARKET STATUS ---
    - Current Price: {market_summary.get('last_price')}
    - 15m HTF Trend: {market_summary.get('htf_bias')}
    - Detected Patterns: {market_summary.get('patterns')}
    - Volume Status: {market_summary.get('volume_status')}

    --- DECISION RULES ---
    1. If market trend has reversed AGAINST our active trade (e.g., active BUY, but 15m HTF turned bearish or major opposing rejection candle), output action: "CLOSE".
    2. If a Market Structure Break (CHoCH/BOS) against our trade formed, output action: "CLOSE".
    3. Otherwise output action: "HOLD".

    Return ONLY raw JSON:
    {{
      "action": "CLOSE" | "HOLD",
      "reason": "Detailed explanation in Urdu/English why trade must be closed immediately."
    }}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        res_data = await asyncio.to_thread(_fetch_gemini_response, url, payload, headers)
        if not res_data:
            return {"action": "HOLD", "reason": "AI offline"}

        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text.replace("```", "").strip()

        return json.loads(raw_text)
    except Exception as e:
        logger.error(f"Reversal Check Error for {symbol}: {e}")
        return {"action": "HOLD", "reason": str(e)}
