# strategy.py
import pandas as pd
from indicators import add_indicators
from config import (
    MIN_SCORE_FOR_SIGNAL, SL_MULTIPLIERS, TP_MULTIPLIERS,
    SL_ATR_MULTIPLIER, TP_ATR_MULTIPLIER,
)


def _agreement(tf_dfs: dict) -> str:
    """Higher TFs ka direction consensus."""
    trends = [df["trend"].iloc[-1] for df in tf_dfs.values() if not df.empty and "trend" in df.columns]
    if not trends:
        return "NA"
    if all(t == "up" for t in trends):
        return "up"
    if all(t == "down" for t in trends):
        return "down"
    return "mixed"


def _confluence_score(last: pd.Series) -> int:
    """BOS + FVG + Volume spike — 3 checks."""
    score = 0
    if bool(last.get("bos", False)):        score += 1
    if bool(last.get("fvg", False)):        score += 1
    if bool(last.get("vol_spike", False)):  score += 1
    return score


def compute_signal(symbol: str, tf_data: dict) -> dict:
    """
    tf_data = {"4h": df, "1h": df, "15m": df, ...}
    Returns signal dict — but AI overrides this later.
    """
    # Add indicators to each TF
    tf_dfs = {}
    for tf, df in tf_data.items():
        if df is None or df.empty:
            continue
        tf_dfs[tf] = add_indicators(df)

    if not tf_dfs:
        return _hold(symbol, "No data")

    direction = _agreement(tf_dfs)
    if direction == "mixed" or direction == "NA":
        return _hold(symbol, "HTF trend conflict")

    # Lowest TF = entry TF
    entry_tf = list(tf_dfs.keys())[-1]
    last = tf_dfs[entry_tf].iloc[-1]

    score = _confluence_score(last)
    if score < MIN_SCORE_FOR_SIGNAL:
        return _hold(symbol, f"Confluence {score}/3")

    atr_val = float(last.get("atr", 0) or 0)
    if atr_val <= 0:
        return _hold(symbol, "ATR=0")

    close = float(last["close"])
    sl_mult = SL_MULTIPLIERS.get(symbol, SL_ATR_MULTIPLIER)
    tp_mult = TP_MULTIPLIERS.get(symbol, TP_ATR_MULTIPLIER)

    if direction == "up":
        signal = "BUY"
        sl = close - sl_mult * atr_val
        tp = close + tp_mult * atr_val
    else:
        signal = "SELL"
        sl = close + sl_mult * atr_val
        tp = close - tp_mult * atr_val

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": int(60 + score * 10),
        "reason": f"HTF {direction}, confluence {score}/3",
        "entry": round(close, 5),
        "stop_loss": round(sl, 5),
        "take_profit": round(tp, 5),
        "top_indicators": ["BOS", "FVG", "Volume"],
    }


def _hold(symbol: str, reason: str) -> dict:
    return {
        "symbol": symbol, "signal": "HOLD", "confidence": 0,
        "reason": reason, "entry": 0, "stop_loss": 0,
        "take_profit": 0, "top_indicators": [],
    }