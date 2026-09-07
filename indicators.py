"""
Indicator and Smart-Money-Concept (SMC) helper calculations.
PDF Integrated: Marubozu Momentum, Engulfing, Volume 20-SMA Filter, and Traps.
"""

import pandas as pd
import numpy as np
import config


def add_emas(df: pd.DataFrame, fast=50, slow=200) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    return df


def add_adaptive_emas(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) >= 210:
        return add_emas(df, fast=50, slow=200)
    return add_emas(df, fast=20, slow=50)


def add_atr(df: pd.DataFrame, period=getattr(config, "ATR_PERIOD", 14)) -> pd.DataFrame:
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean()
    return df


def add_volume_sma(df: pd.DataFrame, period=20) -> pd.DataFrame:
    """PDF Rule: 20-period Volume Moving Average for institutional filter."""
    df = df.copy()
    df["vol_sma"] = df["volume"].rolling(period).mean()
    df["vol_avg"] = df["vol_sma"]
    return df


addvolumesma = add_volume_sma


def has_above_avg_volume(df: pd.DataFrame, period=20) -> bool:
    """PDF Rule: Check if volume spikes past the 20-period Volume MA."""
    if len(df) < period:
        return True
    last_vol = df.iloc[-1]["volume"]
    if last_vol == 0:  # Forex data fallback where volume might be zero
        return True
    vol_sma = df["volume"].tail(period).mean()
    return last_vol > vol_sma


def get_trend_bias(df: pd.DataFrame) -> str:
    last = df.iloc[-1]
    if pd.isna(last["ema_slow"]):
        return "neutral"
    if last["ema_fast"] > last["ema_slow"] and last["close"] > last["ema_fast"]:
        return "bullish"
    if last["ema_fast"] < last["ema_slow"] and last["close"] < last["ema_fast"]:
        return "bearish"
    return "neutral"


def get_htf_bias(df: pd.DataFrame) -> str:
    if "ema_fast" not in df.columns or "ema_slow" not in df.columns:
        df = add_adaptive_emas(df)
    return get_trend_bias(df)


gethtfbias = get_htf_bias


def find_last_swing(df: pd.DataFrame, lookback=30, window=3):
    recent = df.tail(lookback).reset_index(drop=True)
    highs, lows = recent["high"], recent["low"]

    swing_high_idx, swing_low_idx = None, None
    for i in range(window, len(recent) - window):
        window_slice_h = highs[i - window:i + window + 1]
        window_slice_l = lows[i - window:i + window + 1]
        if highs[i] == window_slice_h.max():
            swing_high_idx = i
        if lows[i] == window_slice_l.min():
            swing_low_idx = i

    swing_high = highs[swing_high_idx] if swing_high_idx is not None else highs.max()
    swing_low = lows[swing_low_idx] if swing_low_idx is not None else lows.min()
    return swing_high, swing_low


def detect_marubozu(df: pd.DataFrame, min_body_ratio=0.82) -> str:
    """PDF Rule 1: High Momentum Candle (Marubozu) - Large body, microscopic wicks."""
    if len(df) < 1:
        return "none"
    last = df.iloc[-1]
    total_range = last["high"] - last["low"]
    if total_range == 0:
        return "none"
    body = abs(last["close"] - last["open"])
    if (body / total_range) >= min_body_ratio:
        return "bullish_marubozu" if last["close"] > last["open"] else "bearish_marubozu"
    return "none"


def detect_engulfing(df: pd.DataFrame) -> str:
    """PDF Rule 2: Two-candle pattern fully absorbing previous range."""
    if len(df) < 2:
        return "none"
    c1, c2 = df.iloc[-2], df.iloc[-1]
    if c1["close"] < c1["open"] and c2["close"] > c2["open"]:
        if c2["close"] >= c1["open"] and c2["open"] <= c1["close"]:
            return "bullish_engulfing"
    if c1["close"] > c1["open"] and c2["close"] < c2["open"]:
        if c2["close"] <= c1["open"] and c2["open"] >= c1["close"]:
            return "bearish_engulfing"
    return "none"


def detect_fvg(df: pd.DataFrame, lookback=3) -> str:
    last3 = df.tail(lookback).reset_index(drop=True)
    if len(last3) < 3:
        return "none"
    c0, c2 = last3.iloc[0], last3.iloc[2]
    if c0["high"] < c2["low"]:
        return "bullish_fvg"
    if c0["low"] > c2["high"]:
        return "bearish_fvg"
    return "none"


def detect_rejection_candle(df: pd.DataFrame) -> str:
    if len(df) < 1:
        return "none"
    last = df.iloc[-1]
    total_range = last["high"] - last["low"]
    if total_range == 0:
        return "none"
    body = abs(last["close"] - last["open"])
    upper_wick = last["high"] - max(last["open"], last["close"])
    lower_wick = min(last["open"], last["close"]) - last["low"]

    if lower_wick >= 2 * body and lower_wick >= 0.4 * total_range:
        return "bullish_rejection"
    if upper_wick >= 2 * body and upper_wick >= 0.4 * total_range:
        return "bearish_rejection"
    return "none"


def detect_fake_breakout(df: pd.DataFrame, lookback=10) -> str:
    """PDF Rule 3 & 4: Traps returning back inside range on low volume."""
    if len(df) < lookback:
        return "none"
    recent = df.tail(lookback)
    last = recent.iloc[-1]
    prior = recent.iloc[:-1]

    if last["low"] < prior["low"].min() and last["close"] > prior["low"].min():
        return "bullish_fakeout"  # Bear trap
    if last["high"] > prior["high"].max() and last["close"] < prior["high"].max():
        return "bearish_fakeout"  # Bull trap
    return "none"


def is_in_golden_pocket(price: float, swing_high: float, swing_low: float, direction: str) -> bool:
    diff = swing_high - swing_low
    if diff <= 0:
        return False
    if direction == "bullish":
        return (swing_high - diff * 0.705) <= price <= (swing_high - diff * 0.618)
    elif direction == "bearish":
        return (swing_low + diff * 0.618) <= price <= (swing_low + diff * 0.705)
    return False


def volume_spike_confirms(df: pd.DataFrame, multiplier=1.2, period=20) -> bool:
    return has_above_avg_volume(df, period=period)
