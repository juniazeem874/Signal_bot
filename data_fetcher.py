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

TF_BINANCE = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
TF_BITGET  = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
TF_BYBIT   = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}
TF_TD      = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1day"}
TF_YF      = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h", "1d": "1d"}

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL = 60


# ==================== INDICATORS ====================
def _ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def _macd(series, fast=12, slow=26, signal=9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def _detect_trend(df):
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


def _detect_bos(df, lookback=20):
    if len(df) < lookback + 1:
        return False
    rh = df["high"].iloc[-lookback:-1].max()
    rl = df["low"].iloc[-lookback:-1].min()
    lc = df["close"].iloc[-1]
    return bool(lc > rh or lc < rl)


def _detect_fvg(df):
    if len(df) < 3:
        return False
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    return bool(c1["high"] < c3["low"] or c1["low"] > c3["high"])


def add_indicators(df):
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
def _cache_get(key):
    if key in _CACHE:
        ts, df = _CACHE[key]
        if time.time() - ts < CACHE_TTL:
            return df.copy()
    return None


def _cache_set(key, df):
    _CACHE[key] = (time.time(), df)


# ==================== BINANCE ====================
def fetch_binance(symbol, interval="15m", limit=CANDLES_PER_TF):
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
            log.warning(f"Binance {url} fail {symbol}: {e}")
    return pd.DataFrame()


# ==================== BITGET ====================
def fetch_bitget(symbol, interval="15m", limit=CANDLES_PER_TF):
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
            return pd.DataFrame()
        df = pd.DataFrame(js["data"], columns=["time","open","high","low","close","volume","quoteVol"])
        df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["time","open","high","low","close","volume"]].sort_values("time").reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.warning(f"Bitget fail {symbol}: {e}")
        return pd.DataFrame()


# ==================== BYBIT ====================
def fetch_bybit(symbol, interval="15m", limit=CANDLES_PER_TF):
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
            return pd.DataFrame()
        df = pd.DataFrame(js["result"]["list"], columns=["time","open","high","low","close","volume","turnover"])
        df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms")
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["time","open","high","low","close","volume"]].sort_values("time").reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.warning(f"Bybit fail {symbol}: {e}")
        return pd.DataFrame()


# ==================== TWELVEDATA ====================
def fetch_twelvedata(symbol, interval="1h", outputsize=CANDLES_PER_TF):
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
        # ⭐ FIX: Volume column missing ho to 0
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        else:
            df["volume"] = 0.0
        df = df.rename(columns={"datetime": "time"}).sort_values("time").reset_index(drop=True)
        df = df[["time", "open", "high", "low", "close", "volume"]]
        _cache_set(key, df)
        return df
    except Exception as e:
        log.error(f"TwelveData exception {symbol}: {e}")
        return pd.DataFrame()

# ==================== YFINANCE (FOREX) ====================
def fetch_yfinance(symbol, interval="1h", period="60d"):
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
        df = yf.download(yf_sym, interval=yf_interval, period=period,
                         progress=False, auto_adjust=False, threads=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [(str(c[0]).lower() if isinstance(c, tuple) else str(c).lower()) for c in df.columns]
        df = df.rename(columns={"date": "time", "datetime": "time"})
        df = df[["time","open","high","low","close","volume"]].dropna().reset_index(drop=True)
        _cache_set(key, df)
        return df
    except Exception as e:
        log.warning(f"yfinance fail {symbol}: {e}")
        return pd.DataFrame()


# ==================== FOREX FREE FALLBACKS ====================
def fetch_forex_free(symbol, interval="1h", limit=200):
    """frankfurter.app + exchangerate.host fallback."""
    try:
        base, quote = symbol.split("/")
    except ValueError:
        return pd.DataFrame()

    key = f"fxfree:{symbol}:{interval}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # --- frankfurter.app ---
    try:
        end = pd.Timestamp.utcnow().date()
        start = end - pd.Timedelta(days=90)
        url = f"https://api.frankfurter.app/{start}..{end}"
        r = requests.get(url, params={"from": base, "to": quote}, timeout=10)
        r.raise_for_status()
        rates = r.json().get("rates", {})
        if rates:
            rows = []
            for day, rd in sorted(rates.items()):
                price = rd.get(quote)
                if price:
                    rows.append({"time": pd.to_datetime(day),
                                 "open": price, "high": price,
                                 "low": price, "close": price, "volume": 0})
            if rows:
                df = pd.DataFrame(rows).set_index("time").resample("1h").ffill().reset_index()
                df = df.tail(limit).reset_index(drop=True)
                _cache_set(key, df)
                log.info(f"✅ frankfurter {symbol}: {len(df)} rows")
                return df
    except Exception as e:
        log.warning(f"frankfurter fail {symbol}: {e}")

    # --- exchangerate.host ---
    try:
        end = pd.Timestamp.utcnow().date()
        start = end - pd.Timedelta(days=60)
        url = "https://api.exchangerate.host/timeseries"
        params = {"start_date": str(start), "end_date": str(end), "base": base, "symbols": quote}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        rates = r.json().get("rates", {})
        if rates:
            rows = []
            for day, rd in sorted(rates.items()):
                price = rd.get(quote)
                if price:
                    rows.append({"time": pd.to_datetime(day),
                                 "open": price, "high": price,
                                 "low": price, "close": price, "volume": 0})
            if rows:
                df = pd.DataFrame(rows).set_index("time").resample("1h").ffill().reset_index()
                df = df.tail(limit).reset_index(drop=True)
                _cache_set(key, df)
                log.info(f"✅ exchangerate.host {symbol}: {len(df)} rows")
                return df
    except Exception as e:
        log.warning(f"exchangerate.host fail {symbol}: {e}")

    log.error(f"All forex sources failed for {symbol}")
    return pd.DataFrame()


# ==================== CRYPTO MASTER ====================
def fetch_crypto(symbol, interval="15m", limit=CANDLES_PER_TF):
    """Bitget → Bybit → Binance."""
    df = fetch_bitget(symbol, interval, limit)
    if not df.empty:
        return df
    df = fetch_bybit(symbol, interval, limit)
    if not df.empty:
        return df
    df = fetch_binance(symbol, interval, limit)
    return df if not df.empty else pd.DataFrame()


# ==================== MULTI-TF ====================
def fetch_crypto_multi_tf(symbol):
    out = {}
    for tf in CRYPTO_TFS:
        df = fetch_crypto(symbol, interval=TF_BINANCE.get(tf, tf), limit=CANDLES_PER_TF)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


def fetch_forex_multi_tf(symbol):
    out = {}
    for tf in FOREX_TFS:
        df = fetch_yfinance(symbol, interval=tf)
        if df.empty:
            log.info(f"yfinance empty {symbol} {tf} → free fallback")
            df = fetch_forex_free(symbol, interval=tf)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


def fetch_gold_multi_tf():
    out = {}
    for tf in METAL_TFS:
        df = fetch_twelvedata(GOLD_PAIR, interval=tf, outputsize=CANDLES_PER_TF)
        if not df.empty:
            out[tf] = add_indicators(df)
    return out


# ==================== MASTER ====================
def fetch_all_pairs_raw():
    all_data = {}
    for sym in CRYPTO_PAIRS:
        try:
            d = fetch_crypto_multi_tf(sym)
            if d:
                all_data[sym] = d
        except Exception as e:
            log.error(f"Crypto fail {sym}: {e}")
    for sym in FOREX_PAIRS:
        try:
            d = fetch_forex_multi_tf(sym)
            if d:
                all_data[sym] = d
        except Exception as e:
            log.error(f"Forex fail {sym}: {e}")
    for sym in METAL_PAIRS:
        try:
            d = fetch_gold_multi_tf()
            if d:
                all_data[GOLD_PAIR] = d
        except Exception as e:
            log.error(f"Gold fail: {e}")
    log.info(f"✅ Fetched data for {len(all_data)} pairs")
    return all_data


# ==================== LEGACY ====================
def get_data(symbol):
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


# ==================== PRICE HELPERS ====================
def get_current_price(symbol: str) -> float:
    """Ek pair ka current last-close price lao — har analysis ke liye."""
    try:
        if symbol in CRYPTO_PAIRS:
            df = fetch_crypto(symbol, interval="15m", limit=5)
        elif symbol in FOREX_PAIRS:
            df = fetch_yfinance(symbol, interval="1h", period="7d")
            if df.empty:
                df = fetch_forex_free(symbol, interval="1h")
        elif symbol == GOLD_PAIR:
            df = fetch_twelvedata(symbol, interval="15m", outputsize=5)
        else:
            return 0.0
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception as e:
        log.warning(f"get_current_price fail {symbol}: {e}")
    return 0.0