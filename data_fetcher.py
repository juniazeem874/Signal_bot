import requests
import pandas as pd
import yfinance as yf
import logging
import config

logger = logging.getLogger(__name__)

# Track if TwelveData limit reached for the day
TWELVEDATA_LIMIT_REACHED = False


def get_data_binance(symbol: str, interval: str, limit: int = 500):
    """Fetch Crypto candles directly from Binance."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=[
                'time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
            ])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"Binance fetch error for {symbol}: {e}")
    return None


def get_data_twelvedata(symbol: str, interval: str, limit: int = 500):
    """Fetch Forex/Gold candles from TwelveData."""
    global TWELVEDATA_LIMIT_REACHED

    if TWELVEDATA_LIMIT_REACHED:
        return None

    api_key = getattr(config, "TWELVEDATA_API_KEY", "")
    if not api_key:
        return None

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={limit}&apikey={api_key}"
    try:
        res = requests.get(url, timeout=10)
        json_data = res.json()

        if res.status_code == 200 and "values" in json_data:
            df = pd.DataFrame(json_data["values"])
            df["time"] = pd.to_datetime(df["datetime"])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float) if col in df.columns else 0.0
            df = df.sort_values("time").reset_index(drop=True)
            return df[["time", "open", "high", "low", "close", "volume"]]

        if json_data.get("code") == 429 or "api key" in str(json_data.get("message")).lower():
            logger.warning("⚠️ TwelveData limit reached! Switching to Yahoo Finance Fallback.")
            TWELVEDATA_LIMIT_REACHED = True

    except Exception as e:
        logger.error(f"TwelveData error for {symbol}: {e}")

    return None


def get_data_yfinance(symbol: str, interval: str = "1m"):
    """UNLIMITED FALLBACK: Dynamic loader for Gold, Crypto & Forex Currency Pairs."""
    yf_symbol_map = {
        "XAU/USD": "GC=F",
        "BTCUSDT": "BTC-USD",
        "ETHUSDT": "ETH-USD",
        "SOLUSDT": "SOL-USD",
    }

    if symbol in yf_symbol_map:
        yf_symbol = yf_symbol_map[symbol]
    elif "/" in symbol:
        yf_symbol = symbol.replace("/", "") + "=X"
    else:
        yf_symbol = symbol

    yf_interval = "1m" if interval in ["1m", "1min"] else "15m"
    period = "1d" if yf_interval == "1m" else "5d"

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=yf_interval)
        if not df.empty:
            df = df.reset_index()
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df = df.rename(columns={
                time_col: "time",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume"
            })
            df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
            return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(f"Yahoo Finance fallback error for {symbol} ({yf_symbol}): {e}")

    return None


def get_data(symbol: str):
    """Main router with automatic failover."""
    entry_tf_binance = getattr(config, "ENTRY_INTERVAL_BINANCE", "1m")
    trend_tf_binance = getattr(config, "TREND_INTERVAL_BINANCE", "15m")
    entry_tf_td = getattr(config, "ENTRY_INTERVAL_TWELVEDATA", "1min")
    trend_tf_td = getattr(config, "TREND_INTERVAL_TWELVEDATA", "15min")

    if any(crypto in symbol for crypto in ["USDT", "BTC", "ETH", "SOL"]):
        entry_df = get_data_binance(symbol, entry_tf_binance)
        trend_df = get_data_binance(symbol, trend_tf_binance)
        if entry_df is not None and trend_df is not None:
            return entry_df, trend_df

    entry_df = get_data_twelvedata(symbol, entry_tf_td)
    trend_df = get_data_twelvedata(symbol, trend_tf_td)

    if entry_df is None or entry_df.empty or trend_df is None or trend_df.empty:
        logger.info(f"🔄 Fetching {symbol} via Yahoo Finance Fallback...")
        entry_df = get_data_yfinance(symbol, interval="1m")
        trend_df = get_data_yfinance(symbol, interval="15m")

    return entry_df, trend_df
