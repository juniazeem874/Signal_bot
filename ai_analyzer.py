import json
import requests
import asyncio
import logging
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

# Finnhub's economic calendar "country" field uses ISO-ish country codes
# (US, EU, GB, JP...), NOT currency codes (USD, EUR, GBP, JPY...). The old
# version compared currency code directly against country code, which meant
# it (almost) never matched anything except USD/US — so "high-impact news"
# was silently never detected for any other pair.
_CURRENCY_TO_COUNTRIES = {
    "USD": ["US"],
    "EUR": ["EU", "DE", "FR", "IT", "ES"],
    "GBP": ["GB", "UK"],
    "JPY": ["JP"],
    "AUD": ["AU"],
    "CAD": ["CA"],
    "CHF": ["CH"],
    "NZD": ["NZ"],
}


def _base_currency(symbol: str) -> str:
    s = symbol.upper().strip()
    if "/" in s:
        base, quote = s.split("/", 1)
        if base in _CURRENCY_TO_COUNTRIES:
            return base
        if quote in _CURRENCY_TO_COUNTRIES:
            return quote
        return "USD"
    # No slash (e.g. crypto pairs like BTCUSDT) — not a forex/news-driven pair.
    return "USD"


def get_economic_news(symbol: str) -> dict:
    """
    Fetches today's high-impact economic calendar events relevant to `symbol`'s
    base currency, using Finnhub's free economic calendar endpoint.
    Requires FINNHUB_API_KEY in config/env — without it, returns a neutral
    status instead of failing (get a free key at finnhub.io).
    """
    currency = _base_currency(symbol)
    countries = _CURRENCY_TO_COUNTRIES.get(currency, ["US"])
    api_key = getattr(config, "FINNHUB_API_KEY", "")

    if not api_key:
        return {
            "currency": currency,
            "news_status": "No news feed configured (set FINNHUB_API_KEY)",
            "upcoming_events": "Unknown — AI should rely on price action only"
        }

    try:
        today = datetime.utcnow().date()
        params = {
            "from": today.isoformat(),
            "to": (today + timedelta(days=1)).isoformat(),
            "token": api_key,
        }
        res = requests.get("https://finnhub.io/api/v1/calendar/economic", params=params, timeout=8)

        if res.status_code != 200:
            logger.warning(f"Finnhub calendar HTTP {res.status_code}")
            return {
                "currency": currency,
                "news_status": "News feed unavailable (API error)",
                "upcoming_events": "Unknown"
            }

        data = res.json().get("economicCalendar", [])
        relevant = [
            ev for ev in data
            if ev.get("country") in countries and ev.get("impact") in ("high", "medium")
        ]

        if not relevant:
            return {
                "currency": currency,
                "news_status": "Normal Market Hours (No High-Impact Events Today)",
                "upcoming_events": "None"
            }

        events_summary = [
            f"{ev.get('event')} ({ev.get('impact')} impact) at {ev.get('time')}"
            for ev in relevant[:3]
        ]
        return {
            "currency": currency,
            "news_status": "High/Medium Impact Events Today",
            "upcoming_events": events_summary
        }

    except Exception as e:
        logger.warning(f"Could not fetch live news feed: {e}")
        return {
            "currency": currency,
            "news_status": "News feed unavailable (exception)",
            "upcoming_events": "Unknown"
        }


def _build_prompt(symbol: str, market_summary: dict) -> str:
    news = market_summary.get('news_data', {}) or {}
    return f"""
    You are an Active Institutional Exness Scalper. Your job is to find active BUY or SELL scalping trades on 1m timeframe using 15m HTF alignment. You must weigh BOTH the technical setup AND the news/economic-calendar status below — do not ignore the news section.

    --- MARKET DATA ---
    - Pair: {symbol}
    - Live Price: {market_summary.get('last_price')}
    - 15m HTF Trend: {market_summary.get('htf_bias')}
    - Price Patterns / Rejections: {market_summary.get('patterns')}
    - Swing High: {market_summary.get('swing_high')} | Swing Low: {market_summary.get('swing_low')}
    - ATR Volatility: {market_summary.get('atr')}
    - Exness Spread Buffer: {market_summary.get('exness_buffer')}

    --- NEWS / ECONOMIC CALENDAR ---
    - Currency: {news.get('currency')}
    - Status: {news.get('news_status')}
    - Upcoming High-Impact Events: {news.get('upcoming_events')}

    --- SCALPING EXECUTION RULES ---
    1. If 15m HTF Trend is BULLISH and 1m price is creating higher lows / rejection candles, generate "BUY".
    2. If 15m HTF Trend is BEARISH and 1m price is creating lower highs / rejection candles, generate "SELL".
    3. Do NOT stay in HOLD if there is a clear directional push or pattern alignment with 15m trend.
    4. If a high-impact news event is imminent for this pair's currency, lower confidence or prefer HOLD — news volatility can invalidate technical setups. If there is no high-impact news pending, say so explicitly as a positive factor.
    5. Do NOT propose a trade at all unless the setup realistically has room to run at least 3x the stop distance before hitting the opposing swing level — if the nearest opposing structure is closer than that, prefer HOLD instead of a cramped trade.
    6. Set Confidence between 60% to 95% based on setup quality, adjusted down if high-impact news is pending.
    7. "reasons" MUST contain exactly 3 short items: [0] the core technical setup reason, [1] the Exness execution/risk logic, [2] an explicit statement of how the news/economic-calendar status above factored into this decision (even if the answer is "no high-impact news, so no adjustment made").

    --- STOP LOSS RULES (read carefully — this is the only price level you set) ---
    Take-profit levels are NOT your job — a fixed 1:1 / 1:2 / 1:3 target ladder gets computed automatically from your stop_loss. Your only price-placement task is the stop_loss, and it must be TIGHT and structurally justified, not a wide, arbitrary buffer:
    - For BUY: stop_loss = just below the nearest of (the last rejection wick's low, the most recent swing low, or 1x ATR below entry) — whichever is CLOSEST to entry while still sitting beyond real invalidation. Do not pad it further "for safety" — a wide stop makes every target proportionally wider and harder to reach.
    - For SELL: mirror the same logic above entry.
    - Include the Exness spread buffer ({market_summary.get('exness_buffer')}) in the stop distance, but nowhere else.
    - A stop distance much wider than 1x ATR is a signal you don't have a clean setup — prefer HOLD over forcing a trade with an oversized stop.

    Return ONLY valid raw JSON format, no markdown fences, no commentary:
    {{
      "signal": "BUY" | "SELL" | "HOLD",
      "confidence": number,
      "stop_loss": number,
      "reasons": [
        "Core technical setup reason",
        "Exness execution & risk logic",
        "News/economic-calendar factor"
      ]
    }}
    """


def _parse_ai_json(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text.replace("```", "").strip()
    return json.loads(raw_text)


def _apply_confidence_gate(parsed: dict) -> dict:
    min_conf = getattr(config, "MIN_AI_CONFIDENCE", 65)
    if parsed.get("confidence", 0) < min_conf:
        parsed["signal"] = "HOLD"
        parsed["reasons"] = [f"Confidence ({parsed.get('confidence')}%) below active threshold ({min_conf}%)."]
    return parsed


# ==================== GROQ (sole AI provider) ====================
# Groq retires/renames models periodically (e.g. llama-3.3-70b-versatile was
# decommissioned 2026-08-16) — trying a short fallback list here means the
# bot doesn't go silent again the way it did when gemini-1.5-flash died.
GROQ_MODEL_FALLBACKS = ["openai/gpt-oss-20b", "qwen/qwen3.6-27b"]


def _fetch_groq_response(payload: dict, headers: dict):
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload, headers=headers, timeout=15
        )
        if response.status_code == 200:
            return response.json(), response.status_code
        logger.error(f"Groq API Error {response.status_code}: {response.text[:300]}")
        return None, response.status_code
    except Exception as e:
        logger.error(f"Groq Request Failed: {e}")
        return None, None


async def _call_groq(symbol: str, prompt: str) -> dict:
    api_key = getattr(config, "GROQ_API_KEY", "")
    if not api_key:
        logger.error(
            "GROQ_API_KEY is not set — every signal will silently come back HOLD. "
            "Set GROQ_API_KEY in Railway's Environment tab and redeploy."
        )
        return None

    primary_model = getattr(config, "GROQ_MODEL", "openai/gpt-oss-120b")
    models_to_try = [primary_model] + [m for m in GROQ_MODEL_FALLBACKS if m != primary_model]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        res_data = None
        for model_name in models_to_try:
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            }
            res_data, status_code = await asyncio.to_thread(_fetch_groq_response, payload, headers)
            if res_data:
                if model_name != primary_model:
                    logger.warning(f"Primary Groq model '{primary_model}' failed — used fallback '{model_name}' instead.")
                break
            if status_code in (400, 404):
                # 400 on Groq is what a decommissioned/unknown model_id returns.
                logger.warning(f"Groq model '{model_name}' unavailable/retired — trying next fallback.")
                continue
            break  # other errors (auth/quota/network) won't be fixed by switching models

        if not res_data:
            return None

        raw_text = res_data["choices"][0]["message"]["content"]
        return _apply_confidence_gate(_parse_ai_json(raw_text))
    except Exception as e:
        logger.error(f"Groq processing exception for {symbol}: {e}")
        return None


# ==================== PUBLIC ENTRY POINT ====================

async def analyze_market_with_ai(symbol: str, market_summary: dict) -> dict:
    prompt = _build_prompt(symbol, market_summary)
    return await _call_groq(symbol, prompt)
