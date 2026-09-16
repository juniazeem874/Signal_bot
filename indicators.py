# indicators.py
import pandas as pd
import numpy as np


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(length).mean()
    loss  = (-delta.clip(upper=0)).rolling(length).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast   = ema(series, fast)
    ema_slow   = ema(series, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist       = macd_line - signal_line
    return macd_line, signal_line, hist


def detect_trend(df: pd.DataFrame) -> str:
    """EMA20 vs EMA50 vs EMA200 se simple trend label."""
    if len(df) < 200:
        return "NA"
    last = df.iloc[-1]
    if last["ema20"] > last["ema50"] > last["ema200"]:
        return "up"
    if last["ema20"] < last["ema50"] < last["ema200"]:
        return "down"
    return "sideways"


def detect_bos(df: pd.DataFrame, lookback: int = 20) -> bool:
    """Break of Structure — recent high/low break."""
    if len(df) < lookback + 1:
        return False
    recent_high = df["high"].iloc[-lookback:-1].max()
    recent_low  = df["low"].iloc[-lookback:-1].min()
    last_close  = df["close"].iloc[-1]
    return last_close > recent_high or last_close < recent_low


def detect_fvg(df: pd.DataFrame) -> bool:
    """Fair Value Gap — 3-candle imbalance."""
    if len(df) < 3:
        return False
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    bullish_fvg = c1["high"] < c3["low"]
    bearish_fvg = c1["low"]  > c3["high"]
    return bool(bullish_fvg or bearish_fvg)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Poora indicator stack ek saath add karo."""
    if df is None or df.empty:
        return df
    df = df.copy()
    df["ema20"]  = ema(df["close"], 20)
    df["ema50"]  = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"]    = rsi(df["close"], 14)
    df["atr"]    = atr(df, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["close"])
    df["vol_avg"]   = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] > 1.5 * df["vol_avg"]
    df["trend"]     = detect_trend(df)
    df["bos"]       = detect_bos(df)
    df["fvg"]       = detect_fvg(df)
    return df