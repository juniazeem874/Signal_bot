# data_fetcher.py
import logging
import requests
import pandas as pd
import yfinance as yf
from config import (
    TWELVEDATA_API_KEY, GOLD_PAIR,
    CRYPTO_TFS, FOREX_TFS,
    CRYPTO_PAIRS, FOREX_PAIRS,
)

log = logging.getLogger(__name__)

BINANCE_URL     = "https://api.binance.com/api/v3/klines"
TWELVEDATA_URL  = "https://api.twelvedata.com/time_series"

TF_MAP_BINANCE  = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}
TF_MAP_TD       = {"15m": "15min", "1h": "1h", "4h": "4h"}


# ==================== BINANCE (CRYPTO) ====================
def fetch_binance(symbol: str, interval: str = "15m", limit: int = 300) -> pd.DataFrame:
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        r = requests.get(BINANCE_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbb", "tbq", "ignore",
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c])
        df["time"] = pd.to_datetime(df["open_time"], unit="ms")
        return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    except Exception as e:
        log.error(f"Binance fetch fail {symbol} {interval}: {e}")
        return pd.DataFrame()


# ==================== TWELVEDATA (SIRF GOLD) ====================
def fetch_twelvedata(symbol: str, interval: str = "1h", outputsize: int = 300) -> pd.DataFrame:
    try:
        params = {
            "symbol": symbol,
            "interval": TF_MAP_TD.get(interval, interval),
            "outputsize": outputsize,
            "apikey": TWELVEDATA_API_KEY,
        }
        r = requests.get(TWELVEDATA_URL, params=params, timeout=15)
        r.raise_for_status()
        js = r.json()
        if "values" not in js:
            log.error(f"TwelveData fail {symbol}: {js}")
            return pd.DataFrame()
        df = pd.DataFrame(js["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        for c in ["open", "high", "low", "close"]:
            df[c] = pd.to_numeric(df[c])
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
        df = df.rename(columns={"datetime": "time"}).sort_values("time").reset_index(drop=True)
        return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.error(f"TwelveData exception {symbol}: {e}")
        return pd.DataFrame()


# ==================== YFINANCE (FOREX — FREE) ====================
def fetch_yfinance(symbol: str, interval: str = "1h", period: str = "30d") -> pd.DataFrame:
    """Forex pairs ke liye yfinance (TwelveData quota bachao)."""
    try:
        yf_symbol = symbol.replace("/", "") + "=X"     # EUR/USD → EURUSD=X
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h"}
        df = yf.download(
            yf_symbol,
            interval=tf_map.get(interval, "1h"),
            period=period,
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [str(c).lower() if isinstance(c, tuple) is False else str(c[0]).lower() for c in df.columns]
        df = df.rename(columns={"date": "time", "datetime": "time"})
        return df[["time", "open", "high", "low", "close", "volume"]].dropna()
    except Exception as e:
        log.error(f"yfinance fail {symbol}: {e}")
        return pd.DataFrame()


# ==================== MULTI-TF FETCHERS ====================
def fetch_crypto_multi_tf(symbol: str) -> dict:
    out = {}
    for tf in CRYPTO_TFS:
        out[tf] = fetch_binance(symbol, interval=TF_MAP_BINANCE[tf], limit=300)
    return out


def fetch_forex_multi_tf(symbol: str) -> dict:
    out = {}
    for tf in FOREX_TFS:
        out[tf] = fetch_yfinance(symbol, interval=tf, period="60d")
    return out


def fetch_gold_multi_tf() -> dict:
    """SIRF gold TwelveData se — quota safe."""
    out = {}
    for tf in FOREX_TFS:
        out[tf] = fetch_twelvedata(GOLD_PAIR, interval=tf, outputsize=300)
    return out


def fetch_all_pairs_raw() -> dict:
    """Har pair ka multi-TF data ek dict me."""
    all_data = {}
    for sym in CRYPTO_PAIRS:
        all_data[sym] = fetch_crypto_multi_tf(sym)
    for sym in FOREX_PAIRS:
        all_data[sym] = fetch_forex_multi_tf(sym)
    all_data[GOLD_PAIR] = fetch_gold_multi_tf()
    return all_data