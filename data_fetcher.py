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

BINANCE_HOSTS = [
    "https://data-api.binance.vision",  # public market-data mirror, no geo-block issues
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
]


def _binance_get(path: str, params: dict) -> dict:
    """Try each Binance host in order until one responds successfully.
    Needed because api.binance.com returns HTTP 451 (blocked) from some
    hosting regions, e.g. certain US-based cloud servers."""
    last_error = None
    for host in BINANCE_HOSTS:
        try:
            resp = requests.get(f"{host}{path}", params=params, timeout=10)
            if resp.status_code == 451:
                last_error = f"{host} blocked this region (HTTP 451)"
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = f"{host} failed: {e}"
            continue
    raise ConnectionError(f"All Binance endpoints failed. Last error: {last_error}")


def get_top_crypto_pairs(n=config.CRYPTO_TOP_N, quote=config.CRYPTO_QUOTE_ASSET):
    """Return the top N crypto pairs by 24h quote volume, e.g. ['BTCUSDT', ...]."""
    data = _binance_get("/api/v3/ticker/24hr", {})

    pairs = [d for d in data if d["symbol"].endswith(quote)]
    pairs.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [p["symbol"] for p in pairs[:n]]


def fetch_binance_candles(symbol: str, interval: str, limit: int = config.CANDLE_LIMIT) -> pd.DataFrame:
    """Fetch OHLCV candles for a Binance symbol, e.g. 'BTCUSDT'."""
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    raw = _binance_get("/api/v3/klines", params)

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

# Our internal interval strings (shared with Binance, which uses '15m', '1h',
# '4h', etc.) don't all match what TwelveData expects (it wants '15min' for
# sub-hour intervals). Map them here rather than changing the shared config.
TWELVEDATA_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "45m": "45min",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1day",
}


def fetch_twelvedata_candles(symbol: str, interval: str, limit: int = config.CANDLE_LIMIT) -> pd.DataFrame:
    """Fetch OHLCV candles for a forex/metal symbol, e.g. 'EUR/USD'."""
    if not config.TWELVEDATA_API_KEY:
        raise ValueError("TWELVEDATA_API_KEY is not set. Add it to your environment variables.")

    td_interval = TWELVEDATA_INTERVAL_MAP.get(interval, interval)

    url = f"{TWELVEDATA_BASE}/time_series"
    params = {
        "symbol": symbol.upper(),
        "interval": td_interval,
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


def fetch_multi_timeframe(symbol: str, timeframes: list, limit: int = config.CANDLE_LIMIT) -> dict:
    """Fetch candles for several timeframes of the same symbol.
    Returns {timeframe: dataframe}. Used for top-down multi-timeframe analysis."""
    return {tf: fetch_candles(symbol, tf, limit) for tf in timeframes}
