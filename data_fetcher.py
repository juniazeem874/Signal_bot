# data_fetcher.py
import logging
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf

from config import (
    TWELVEDATA_API_KEY,
    CRYPTO_PAIRS, FOREX_PAIRS, METAL_PAIRS, GOLD_PAIR,
    CRYPTO_TFS, FOREX_TFS, METAL_TFS,
    CANDLES_PER_TF,
)

log = logging.getLogger(__name__)

# ==================== ENDPOINTS ====================
BINANCE_URL    = "https://api.binance.com/api/v3/klines"
BINANCE_US_URL = "https://api.binance.us/api/v3/klines"
BITGET_URL     = "https://api.bitget.com/api/v2/mix/market/candles"
BYBIT_URL      = "https://api.bybit.com/v5/market/kline"
TWELVEDATA_URL = "https://api.twelvedata.com/time_series"

# Interval maps
TF_BINANCE = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
TF_BITGET  = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
TF_BYBIT   = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
TF_TD      = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1day"}
TF_YF      = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}

# Cache
_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL = 60


# ==================== INDICATORS ====================
def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _detect_trend(df: pd.DataFrame) -> str:
    if len(df) < 200:
        return "NA"
    last = df.iloc[-1]
    if pd.isna(last.get("ema20")) or pd.isna(last.get("ema200")):
        return "NA"
    if last["ema20"] > last["ema50"] > last["ema200"]:
        return "up"
    if last["ema20"] < last["ema50"] < last["ema200"]:
        return "down"
    return "sideways"


def _detect_bos(df: pd.DataFrame, lookback: int = 20) -> bool:
    if len(df) < lookback + 1:
        return False
    recent_high = df["high"].iloc[-lookback:-1].max()
    recent_low = df["low"].iloc[-lookback:-1].min()
    last_close = df["close"].iloc[-1]
    return bool(last_close > recent_high or last_close < recent_low)


def _detect_fvg(df: pd.DataFrame) -> bool:
    if len(df) < 3:
        return False
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    bullish = c1["high"] < c3["low"]
    bearish = c1["low"] > c3["high"]
    return bool(bullish or bearish)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or len(df) < 30:
        return df
    df = df.copy()
    df["ema20"] = _ema(df["close"], 20)
    df["ema50"] = _ema(df["close"], 50)
    df["ema200"] = _ema(df["close"], 200)
    df["rsi"] = _rsi(df["close"], 14)
    df["atr"] = _atr(df, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["close"])
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] > 1.5 * df["vol_avg"]
    df["trend"] = _detect_trend(df)
    df["bos"] = _detect_bos(df)
    df["fvg"] = _detect_fvg(df)
    return df


# ==================== CACHE ====================
def _cache_get(key: str) -> pd.DataFrame:
    if key in _CACHE:
        ts, df = _CACHE[key]
        if time.time() - ts < CACHE_TTL:
            return df.copy()
    return None


def _cache_set(key: str, df: pd.DataFrame):
    _CACHE[key] = (time.time(), df)


# ==================== BINANCE ====================
def fetch_binance(symbol: str, interval: str = "15m", limit: int = CANDLES_PER_TF) -> pd.DataFrame:
    key = f"binance:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    for url in [BINANCE_URL, BINANCE_US_URL]:
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list) or not data:
                continue
            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbb", "tbq", "ignore",
            ])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["time"] = pd.to_datetime(df["open_time"], unit="ms")
            df = df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
            _cache_set(key, df)
            return df
        except Exception as e:
            log.warning(f"Binance {url} fail {symbol} {interval}: {e}")
    return pd.DataFrame()


# ==================== BITGET ====================
def fetch_bitget(symbol: str, interval: str = "15m", limit: int = CANDLES_PER_TF) -> pd.DataFrame:
    """Bitget USDT-M futures candles."""
    key = f"bitget:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        params = {
            "symbol": symbol,
            "granularity": TF_BITGET.get(interval, "15m"),
            "limit": min(limit, 1000),
            "productType": "usdt-futures",
        }
        r = requests.get(BITGET_URL, params=params, timeout=10)
        r.raise_for_status()
        js = r.json()
        if js.get("code") != "00000" or not js.get("data"):
            log.warning(f"Bitget empty {symbol}: {js.get('msg')}")
            return pd.DataFrame()
        # Bitget: [timestamp, open, high, low, close, baseVol, quoteVol]
        df = pd.DataFrame(js["data"], columns=[
            "time", "open", "high", "low", "close", "volume", "quoteVol"
        ])
        df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["time", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("time").reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.warning(f"Bitget fail {symbol} {interval}: {e}")
        return pd.DataFrame()


# ==================== BYBIT ====================
def fetch_bybit(symbol: str, interval: str = "15m", limit: int = CANDLES_PER_TF) -> pd.DataFrame:
    """Bybit v5 spot kline."""
    key = f"bybit:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": TF_BYBIT.get(interval, "15"),
            "limit": min(limit, 1000),
        }
        r = requests.get(BYBIT_URL, params=params, timeout=10)
        r.raise_for_status()
        js = r.json()
        if js.get("retCode") != 0 or not js.get("result", {}).get("list"):
            log.warning(f"Bybit empty {symbol}: {js.get('retMsg')}")
            return pd.DataFrame()
        # Bybit: [startTime, open, high, low, close, volume, turnover]
        df = pd.DataFrame(js["result"]["list"], columns=[
            "time", "open", "high", "low", "close", "volume", "turnover"
        ])
        df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["time", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("time").reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.warning(f"Bybit fail {symbol} {interval}: {e}")
        return pd.DataFrame()


# ==================== TWELVEDATA (GOLD) ====================
def fetch_twelvedata(symbol: str, interval: str = "1h", outputsize: int = CANDLES_PER_TF) -> pd.DataFrame:
    """Gold via TwelveData (XAU/USD)."""
    if not TWELVEDATA_API_KEY:
        log.error("TWELVEDATA_API_KEY missing")
        return pd.DataFrame()
    key = f"td:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        params = {
            "symbol": symbol,
            "interval": TF_TD.get(interval, interval),
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
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
        df = df.rename(columns={"datetime": "time"}).sort_values("time").reset_index(drop=True)
        df = df[["time", "open", "high", "low", "close", "volume"]]
        _cache_set(key, df)
        return df
    except Exception as e:
        log.error(f"TwelveData exception {symbol}: {e}")
        return pd.DataFrame()


# ==================== YFINANCE (FOREX) ====================
def fetch_yfinance(symbol: str, interval: str = "1h", period: str = "60d") -> pd.DataFrame:
    """Forex via yfinance (free unlimited)."""
    key = f"yf:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        yf_sym = symbol.replace("/", "") + "=X"
        yf_interval = TF_YF.get(interval, "1h")
        if yf_interval in ("1m", "5m"):
            period = "7d"
        elif yf_interval == "15m":
            period = "60d"
        df = yf.download(
            yf_sym, interval=yf_interval, period=period,
            progress=False, auto_adjust=False, threads=False,
        )
        if df is None or df.empty:
            log.warning(f"yfinance empty: {symbol} {interval}")
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [
            (str(c[0]).lower() if isinstance(c, tuple) else str(c).lower())
            for c in df.columns
        ]
        df = df.rename(columns={"date": "time", "datetime": "time"})
        df = df[["time", "open", "high", "low", "close", "volume"]].dropna()
        df = df.reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.error(f"yfinance fail {symbol}: {e}")
        return pd.DataFrame()


# ==================== CRYPTO FETCHER (3 Fallbacks) ====================
def fetch_crypto(symbol: str, interval: str = "15m", limit: int = CANDLES_PER_TF) -> pd.DataFrame:
    """Try Bitget → Bybit → Binance → Binance.US. First success wins."""
    # 1. Bitget
    df = fetch_bitget(symbol, interval, limit)
    if not df.empty:
        return df
    log.info(f"Bitget failed {symbol}, trying Bybit...")
    # 2. Bybit
    df = fetch_bybit(symbol, interval, limit)
    if not df.empty:
        return df
    log.info(f"Bybit failed {symbol}, trying Binance...")
    # 3. Binance (US + Global)
    df = fetch_binance(symbol, interval, limit)
    if not df.empty:
        return df
    log.warning(f"All crypto sources failed for {symbol}")
    return pd.DataFrame()


# ==================== MULTI-TF FETCHERS ====================
def fetch_crypto_multi_tf(symbol: str) -> dict:
    out = {}
    for tf in CRYPTO_TFS:
        df = fetch_crypto(symbol, interval=TF_BINANCE.get(tf, tf), limit=CANDLES_PER_TF)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


def fetch_forex_multi_tf(symbol: str) -> dict:
    out = {}
    for tf in FOREX_TFS:
        df = fetch_yfinance(symbol, interval=tf)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


def fetch_gold_multi_tf() -> dict:
    """Gold — TwelveData se."""
    out = {}
    for tf in METAL_TFS:
        df = fetch_twelvedata(GOLD_PAIR, interval=tf, outputsize=CANDLES_PER_TF)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


# ==================== MASTER FETCH ====================
def fetch_all_pairs_raw() -> dict:
    """Saare 19 pairs ka multi-TF data."""
    all_data: dict[str, dict] = {}

    # 1. Crypto — Bitget + Bybit + Binance fallback
    for sym in CRYPTO_PAIRS:
        try:
            tf_data = fetch_crypto_multi_tf(sym)
            if tf_data:
                all_data[sym] = tf_data
        except Exception as e:
            log.error(f"Crypto fetch fail {sym}: {e}")

    # 2. Forex — yfinance
    for sym in FOREX_PAIRS:
        try:
            tf_data = fetch_forex_multi_tf(sym)
            if tf_data:
                all_data[sym] = tf_data
        except Exception as e:
            log.error(f"Forex fetch fail {sym}: {e}")

    # 3. Gold — TwelveData
    for sym in METAL_PAIRS:
        try:
            tf_data = fetch_gold_multi_tf()
            if tf_data:
                all_data[GOLD_PAIR] = tf_data
        except Exception as e:
            log.error(f"Gold fetch fail: {e}")

    log.info(f"✅ Fetched data for {len(all_data)} pairs")
    return all_data


# ==================== LEGACY SUPPORT ====================
def get_data(symbol: str):
    """Single pair (entry_df, trend_df)."""
    if symbol in CRYPTO_PAIRS:
        tf_data = fetch_crypto_multi_tf(symbol)
    elif symbol in FOREX_PAIRS:
        tf_data = fetch_forex_multi_tf(symbol)
    elif symbol == GOLD_PAIR:
        tf_data = fetch_gold_multi_tf()
    else:
        return (None, None)
    if not tf_data:
        return (None, None)
    tfs = list(tf_data.keys())
    return (tf_data[tfs[-1]], tf_data[tfs[0]])