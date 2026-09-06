"""
Fetches OHLCV candle data from Binance (crypto) and TwelveData (forex),
and returns it as a pandas DataFrame with columns:
    time, open, high, low, close, volume
"""

import requests
import pandas as pd
import config


# ---------------------------------------------------------------------
# BINANCE (crypto) - free, no API key needed for public market data
# ---------------------------------------------------------------------

BINANCE_BASE = "https://api.binance.com"


def get_top_crypto_pairs(n=config.CRYPTO_TOP_N, quote=config.CRYPTO_QUOTE_ASSET):
    """Return the top N crypto pairs by 24h quote volume, e.g. ['BTCUSDT', ...]."""
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    pairs = [d for d in data if d["symbol"].endswith(quote)]
    pairs.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [p["symbol"] for p in pairs[:n]]


def fetch_binance_candles(symbol: str, interval: str, limit: int = config.CANDLE_LIMIT) -> pd.DataFrame:
    """Fetch OHLCV candles for a Binance symbol, e.g. 'BTCUSDT'."""
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    if not raw or isinstance(raw, dict):
        raise ValueError(f"No data returned for {symbol}. Check the symbol is correct.")

    df = pd.DataFrame(raw, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df[["time", "open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------
# TWELVEDATA (forex) - free tier: 800 requests/day, 8/min. Be sparing.
# ---------------------------------------------------------------------

TWELVEDATA_BASE = "https://api.twelvedata.com"


def fetch_twelvedata_candles(symbol: str, interval: str, limit: int = config.CANDLE_LIMIT) -> pd.DataFrame:
    """Fetch OHLCV candles for a forex/metal symbol, e.g. 'EUR/USD'."""
    if not config.TWELVEDATA_API_KEY:
        raise ValueError("TWELVEDATA_API_KEY is not set. Add it to your environment variables.")

    url = f"{TWELVEDATA_BASE}/time_series"
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "outputsize": limit,
        "apikey": config.TWELVEDATA_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    if raw.get("status") == "error" or "values" not in raw:
        msg = raw.get("message", "Unknown error from TwelveData")
        raise ValueError(f"TwelveData error for {symbol}: {msg}")

    df = pd.DataFrame(raw["values"])
    df["time"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    # TwelveData forex endpoint often has no real volume; default to 0 if missing
    df["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0

    df = df.sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------

def is_forex_symbol(symbol: str) -> bool:
    """Forex/metal symbols contain a slash, e.g. 'EUR/USD'. Crypto ones don't, e.g. 'BTCUSDT'."""
    return "/" in symbol


def fetch_candles(symbol: str, interval: str, limit: int = config.CANDLE_LIMIT) -> pd.DataFrame:
    """Route to the correct data source based on the symbol format."""
    if is_forex_symbol(symbol):
        return fetch_twelvedata_candles(symbol, interval, limit)
    return fetch_binance_candles(symbol, interval, limit)
