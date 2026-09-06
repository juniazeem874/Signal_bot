"""
Indicator and Smart-Money-Concept (SMC) helper calculations.
All functions take/return pandas DataFrames or plain values - no external
TA library needed, keeps deployment on Railway simple.
"""

import pandas as pd
import numpy as np
import config


def add_emas(df: pd.DataFrame, fast=50, slow=200) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    return df


def add_atr(df: pd.DataFrame, period=config.ATR_PERIOD) -> pd.DataFrame:
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean()
    return df


def add_volume_avg(df: pd.DataFrame, period=20) -> pd.DataFrame:
    df = df.copy()
    df["vol_avg"] = df["volume"].rolling(period).mean()
    return df


def get_trend_bias(df: pd.DataFrame) -> str:
    """'bullish', 'bearish', or 'neutral' based on EMA50/200 + price position."""
    last = df.iloc[-1]
    if pd.isna(last["ema_slow"]):
        return "neutral"
    if last["ema_fast"] > last["ema_slow"] and last["close"] > last["ema_fast"]:
        return "bullish"
    if last["ema_fast"] < last["ema_slow"] and last["close"] < last["ema_fast"]:
        return "bearish"
    return "neutral"


def find_last_swing(df: pd.DataFrame, lookback=30, window=3):
    """
    Find the most recent swing high and swing low within the last `lookback`
    candles. A swing high/low is a local max/min over `window` candles on
    each side. Returns (swing_high_price, swing_high_idx, swing_low_price, swing_low_idx).
    """
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


def fibonacci_levels(swing_high: float, swing_low: float) -> dict:
    diff = swing_high - swing_low
    return {
        "0.5": swing_high - diff * 0.5,
        "0.618": swing_high - diff * 0.618,
        "0.786": swing_high - diff * 0.786,
    }


def price_in_fib_zone(price: float, fib: dict, tolerance_pct=0.15) -> bool:
    """True if price sits within the 0.5-0.786 retracement zone (with a little slack)."""
    zone_top = fib["0.5"]
    zone_bottom = fib["0.786"]
    lo, hi = min(zone_top, zone_bottom), max(zone_top, zone_bottom)
    slack = (hi - lo) * tolerance_pct
    return (lo - slack) <= price <= (hi + slack)


def detect_bos(df: pd.DataFrame, lookback=30) -> str:
    """
    Very simplified Break of Structure detector.
    Returns 'bullish_bos' if price closed above the recent swing high,
    'bearish_bos' if it closed below the recent swing low, else 'none'.
    """
    recent = df.tail(lookback)
    prior = recent.iloc[:-1]
    last_close = recent.iloc[-1]["close"]

    if last_close > prior["high"].max():
        return "bullish_bos"
    if last_close < prior["low"].min():
        return "bearish_bos"
    return "none"


def detect_fvg(df: pd.DataFrame, lookback=3) -> str:
    """
    Simplified 3-candle Fair Value Gap detector on the most recent candles.
    Bullish FVG: candle[0].high < candle[2].low (gap left behind in an up-move)
    Bearish FVG: candle[0].low > candle[2].high
    """
    last3 = df.tail(lookback).reset_index(drop=True)
    if len(last3) < 3:
        return "none"
    c0, c2 = last3.iloc[0], last3.iloc[2]
    if c0["high"] < c2["low"]:
        return "bullish_fvg"
    if c0["low"] > c2["high"]:
        return "bearish_fvg"
    return "none"


def volume_confirms(df: pd.DataFrame, direction: str) -> bool:
    """True if the latest candle's volume is above average AND candle color matches direction."""
    last = df.iloc[-1]
    if pd.isna(last["vol_avg"]) or last["vol_avg"] == 0:
        return False
    is_spike = last["volume"] > last["vol_avg"] * 1.2
    bullish_candle = last["close"] > last["open"]
    if direction == "bullish":
        return is_spike and bullish_candle
    if direction == "bearish":
        return is_spike and not bullish_candle
    return False
