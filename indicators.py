"""
Indicator and Smart-Money-Concept (SMC) helper calculations.
Implements VWAP, Fibonacci Golden Pocket, Liquidity Sweeps, Engulfing, and Volume Spikes.
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


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates Volume Weighted Average Price (VWAP)."""
    df = df.copy()
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    tp_vol = typical_price * df["volume"]
    cum_tp_vol = tp_vol.cumsum()
    cum_vol = df["volume"].cumsum().replace(0, 1e-8)
    df["vwap"] = cum_tp_vol / cum_vol
    return df


def add_volume_sma(df: pd.DataFrame, period=config.VOL_SMA_PERIOD) -> pd.DataFrame:
    """Calculates simple moving average of volume."""
    df = df.copy()
    df["vol_sma"] = df["volume"].rolling(period).mean()
    return df


def get_htf_bias(df_15m: pd.DataFrame) -> str:
    """
    Determines HTF (15m) bias based on VWAP & Market Structure:
    - Bullish: Price > VWAP and EMA50 > EMA200
    - Bearish: Price < VWAP and EMA50 < EMA200
    """
    df_15m = add_vwap(df_15m)
    df_15m = add_emas(df_15m)
    last = df_15m.iloc[-1]

    if pd.isna(last["vwap"]):
        return "neutral"

    above_vwap = last["close"] > last["vwap"]
    below_vwap = last["close"] < last["vwap"]
    ema_bullish = last["ema_fast"] > last["ema_slow"]
    ema_bearish = last["ema_fast"] < last["ema_slow"]

    if above_vwap and ema_bullish:
        return "bullish"
    elif below_vwap and ema_bearish:
        return "bearish"
    return "neutral"


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


def fibonacci_levels(swing_high: float, swing_low: float) -> dict:
    diff = swing_high - swing_low
    return {
        "0.0": swing_high,
        "0.5": swing_high - diff * 0.5,
        "0.618": swing_high - diff * 0.618,
        "0.705": swing_high - diff * 0.705,
        "1.0": swing_low,
    }


def is_in_golden_pocket(price: float, swing_high: float, swing_low: float, direction: str) -> bool:
    """Checks if price is inside the 0.618 - 0.705 Golden Pocket retracement zone."""
    diff = swing_high - swing_low
    if diff <= 0:
        return False

    if direction == "bullish":
        # Retracement down from swing high
        gp_top = swing_high - diff * config.FIB_GOLDEN_POCKET_LOW   # 0.618
        gp_bottom = swing_high - diff * config.FIB_GOLDEN_POCKET_HIGH # 0.705
        return gp_bottom <= price <= gp_top
    else:
        # Retracement up from swing low
        gp_bottom = swing_low + diff * config.FIB_GOLDEN_POCKET_LOW
        gp_top = swing_low + diff * config.FIB_GOLDEN_POCKET_HIGH
        return gp_bottom <= price <= gp_top


def detect_bos(df: pd.DataFrame, lookback=20) -> str:
    recent = df.tail(lookback)
    prior = recent.iloc[:-1]
    last_close = recent.iloc[-1]["close"]

    if last_close > prior["high"].max():
        return "bullish_bos"
    if last_close < prior["low"].min():
        return "bearish_bos"
    return "none"


def detect_fvg(df: pd.DataFrame) -> str:
    last3 = df.tail(3).reset_index(drop=True)
    if len(last3) < 3:
        return "none"
    c0, c2 = last3.iloc[0], last3.iloc[2]
    if c0["high"] < c2["low"]:
        return "bullish_fvg"
    if c0["low"] > c2["high"]:
        return "bearish_fvg"
    return "none"


def detect_engulfing(df: pd.DataFrame) -> str:
    """Detects 1-minute Bullish or Bearish Engulfing Candle."""
    if len(df) < 2:
        return "none"
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    # Bullish Engulfing
    if curr["close"] > curr["open"] and prev["close"] < prev["open"]:
        if curr["close"] >= prev["open"] and curr["open"] <= prev["close"]:
            return "bullish_engulfing"

    # Bearish Engulfing
    if curr["close"] < curr["open"] and prev["close"] > prev["open"]:
        if curr["close"] <= prev["open"] and curr["open"] >= prev["close"]:
            return "bearish_engulfing"

    return "none"


def detect_liquidity_sweep(df: pd.DataFrame, lookback=10) -> str:
    """Detects liquidity stop hunt/sweep of recent local swings."""
    if len(df) < lookback + 1:
        return "none"
    recent = df.tail(lookback + 1)
    prev = recent.iloc[:-1]
    curr = recent.iloc[-1]

    if curr["low"] < prev["low"].min() and curr["close"] > prev["low"].min():
        return "bullish_sweep"
    if curr["high"] > prev["high"].max() and curr["close"] < prev["high"].max():
        return "bearish_sweep"
    return "none"


def volume_spike_confirms(df: pd.DataFrame) -> bool:
    """True if latest candle volume >= 1.5x of preceding 5-candle SMA."""
    df = add_volume_sma(df)
    last = df.iloc[-1]
    prev_sma = df.iloc[-2]["vol_sma"] if len(df) > 1 else last["vol_sma"]

    if pd.isna(prev_sma) or prev_sma == 0:
        return False
    return last["volume"] >= prev_sma * config.VOL_SPIKE_MULTIPLIER
    def detect_rejection_candle(df: pd.DataFrame) -> str:
    """
    Detects long-wick Pinbar/Rejection candles.
    Lower wick >= 55% of total candle length -> Bullish Rejection (Demand response).
    Upper wick >= 55% of total candle length -> Bearish Rejection (Supply response).
    """
    if len(df) < 1:
        return "none"
    curr = df.iloc[-1]
    candle_range = curr["high"] - curr["low"]
    if candle_range == 0:
        return "none"

    body = abs(curr["close"] - curr["open"])
    upper_wick = curr["high"] - max(curr["open"], curr["close"])
    lower_wick = min(curr["open"], curr["close"]) - curr["low"]

    if lower_wick / candle_range >= 0.55 and body / candle_range <= 0.35:
        return "bullish_rejection"
    if upper_wick / candle_range >= 0.55 and body / candle_range <= 0.35:
        return "bearish_rejection"
    return "none"


def detect_fake_breakout(df: pd.DataFrame, lookback=15) -> str:
    """
    Detects Fake Breakouts (Liquidity Grab / Traps):
    - Bull Trap (Bearish Fakeout): Price breaks recent high but closes back inside range.
    - Bear Trap (Bullish Fakeout): Price breaks recent low but closes back inside range.
    """
    if len(df) < lookback + 1:
        return "none"
    recent = df.tail(lookback + 1)
    prior = recent.iloc[:-1]
    curr = recent.iloc[-1]

    prior_high = prior["high"].max()
    prior_low = prior["low"].min()

    # Bear Trap: Low todi lekin candle close level ke upar hui (Bullish Signal)
    if curr["low"] < prior_low and curr["close"] > prior_low:
        return "bullish_fakeout"

    # Bull Trap: High toda lekin candle close level ke niche hui (Bearish Signal)
    if curr["high"] > prior_high and curr["close"] < prior_high:
        return "bearish_fakeout"

    return "none"

    
