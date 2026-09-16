# indicators.py
import pandas as pd
import numpy as np


# ==================== BASIC INDICATORS ====================
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def detect_trend(df):
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


def detect_bos(df, lookback=20):
    if len(df) < lookback + 1:
        return False
    rh = df["high"].iloc[-lookback:-1].max()
    rl = df["low"].iloc[-lookback:-1].min()
    lc = df["close"].iloc[-1]
    return bool(lc > rh or lc < rl)


def detect_fvg(df):
    if len(df) < 3:
        return False
    c1, c3 = df.iloc[-3], df.iloc[-1]
    return bool(c1["high"] < c3["low"] or c1["low"] > c3["high"])


# ==================== FIBONACCI RETRACEMENT ====================
def fibonacci_retracement(df, lookback=50):
    """
    Fibonacci retracement levels nikaalo.
    Returns dict with levels, golden zone, current zone.
    """
    if df is None or len(df) < lookback:
        return None

    window = df.tail(lookback)
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())
    current = float(df["close"].iloc[-1])

    if swing_high <= swing_low:
        return None

    diff = swing_high - swing_low

    # Retracement levels (from high down)
    levels = {
        "0.0":   swing_high,
        "0.236": swing_high - 0.236 * diff,
        "0.382": swing_high - 0.382 * diff,
        "0.5":   swing_high - 0.5 * diff,
        "0.618": swing_high - 0.618 * diff,
        "0.786": swing_high - 0.786 * diff,
        "1.0":   swing_low,
    }

    midpoint = (swing_high + swing_low) / 2
    direction = "up" if current > midpoint else "down"

    golden_low = min(levels["0.5"], levels["0.786"])
    golden_high = max(levels["0.5"], levels["0.786"])

    if golden_low <= current <= golden_high:
        current_zone = "IN_GOLDEN_ZONE"
    elif current > levels["0.382"]:
        current_zone = "ABOVE_0.382"
    elif current < levels["0.786"]:
        current_zone = "BELOW_0.786"
    else:
        current_zone = "MID"

    nearest_ratio = "0.5"
    min_dist = float("inf")
    for ratio, price in levels.items():
        d = abs(current - price)
        if d < min_dist:
            min_dist = d
            nearest_ratio = ratio

    nearest_price = levels[nearest_ratio]
    nearest_dist_pct = (min_dist / current) * 100 if current else 0

    return {
        "swing_high": round(swing_high, 6),
        "swing_low":  round(swing_low, 6),
        "direction":  direction,
        "levels":     {k: round(v, 6) for k, v in levels.items()},
        "golden_zone": {
            "low": round(golden_low, 6),
            "high": round(golden_high, 6),
        },
        "current_zone": current_zone,
        "nearest_level": {
            "ratio": nearest_ratio,
            "price": round(nearest_price, 6),
            "distance_pct": round(nearest_dist_pct, 3),
        },
    }


# ==================== MAIN ADD INDICATORS ====================
def add_indicators(df):
    if df is None or df.empty or len(df) < 30:
        return df
    df = df.copy()
    df["ema20"] = ema(df["close"], 20)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi"] = rsi(df["close"], 14)
    df["atr"] = atr(df, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["close"])
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] > 1.5 * df["vol_avg"]
    df["trend"] = detect_trend(df)
    df["bos"] = detect_bos(df)
    df["fvg"] = detect_fvg(df)
    return df