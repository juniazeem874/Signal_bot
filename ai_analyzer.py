import requests
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
