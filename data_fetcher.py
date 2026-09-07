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
    """Try each Binance host in order until one responds successfully."""
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


def get_top_crypto_pairs(n=getattr(config, "CRYPTO_TOP_N", 10), quote=getattr(config, "CRYPTO_QUOTE_ASSET", "USDT")):
    """Return the top N crypto pairs by 24h quote volume."""
    data = _binance_get("/api/v3/ticker/24hr", {})

    pairs = [d for d in data if d["symbol"].endswith(quote)]
    pairs.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [p["symbol"] for p in pairs[:n]]


def fetch_binance_candles(symbol: str, interval: str, limit: int = getattr(config, "CANDLE_LIMIT", 100)) -> pd.DataFrame:
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
# TWELVEDATA (forex) - free tier: 800 requests/day, 8/min.
# ---------------------------------------------------------------------

TWELVEDATA_BASE = "https://api.twelvedata.com"

TWELVEDATA_INTERVAL_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "45m": "45min",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1day",
}


def fetch_twelvedata_candles(symbol: str, interval: str, limit: int = getattr(config, "CANDLE_LIMIT", 100)) -> pd.DataFrame:
    """Fetch OHLCV candles for a forex/metal symbol, e.g. 'EUR/USD'."""
    api_key = getattr(config, "TWELVEDATA_API_KEY", None)
    if not api_key:
        raise ValueError("TWELVEDATA_API_KEY is not set. Add it to your environment variables.")

    td_interval = TWELVEDATA_INTERVAL_MAP.get(interval, interval)

    url = f"{TWELVEDATA_BASE}/time_series"
    params = {
        "symbol": symbol.upper(),
        "interval": td_interval,
        "outputsize": limit,
        "apikey": api_key,
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
    df["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0

    df = df.sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


# ---------------------------------------------------------------------
# Unified Interface & Strategy Wrappers
# ---------------------------------------------------------------------

def is_forex_symbol(symbol: str) -> bool:
    """Forex/metal symbols contain a slash (EUR/USD), crypto symbols do not (BTCUSDT)."""
    return "/" in symbol


def fetch_candles(symbol: str, interval: str, limit: int = getattr(config, "CANDLE_LIMIT", 100)) -> pd.DataFrame:
    """Route to the correct data source based on the symbol format."""
    if is_forex_symbol(symbol):
        return fetch_twelvedata_candles(symbol, interval, limit)
    return fetch_binance_candles(symbol, interval, limit)


def fetch_multi_timeframe(symbol: str, timeframes: list, limit: int = getattr(config, "CANDLE_LIMIT", 100)) -> dict:
    """Fetch candles for several timeframes of the same symbol."""
    return {tf: fetch_candles(symbol, tf, limit) for tf in timeframes}


def get_data(symbol: str):
    """
    Main method required by bot.py to fetch 1m (LTF Entry) 
    and 15m (HTF Trend) data simultaneously.
    """
    entry_tf = getattr(config, "ENTRY_TIMEFRAME", "1m")
    trend_tf = getattr(config, "TREND_TIMEFRAME", "15m")

    entry_df = fetch_candles(symbol, entry_tf)
    trend_df = fetch_candles(symbol, trend_tf)

    return entry_df, trend_df


# Naming Aliases so bot.py works with get_data or getdata
getdata = get_data
