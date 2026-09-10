import requests
import pandas as pd
import yfinance as yf
import logging
import config

logger = logging.getLogger(__name__)

BINANCE_INTERVAL_MAP = {"1min": "1m", "5min": "5m", "15min": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
YFINANCE_INTERVAL_MAP = {"1min": "1m", "5min": "5m", "15min": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}

def fetch_binance_crypto(symbol: str, interval="1min", outputsize=100):
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()
    if clean_symbol.endswith("USD") and not clean_symbol.endswith("USDT"):
        clean_symbol += "T"
    if not (clean_symbol.endswith("USDT") or clean_symbol.endswith("BUSD")):
        clean_symbol += "USDT"

    b_interval = BINANCE_INTERVAL_MAP.get(interval, "1m")
    url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval={b_interval}&limit={outputsize}"

    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return None

        data = res.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "count", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore"
        ])
        df['time'] = pd.to_datetime(df['open_time'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"Binance fetch error for {symbol}: {e}")
        return None


def fetch_twelvedata_forex(symbol: str, interval="1min", outputsize=100):
    api_key = getattr(config, "TWELVEDATA_API_KEY", "")
    if not api_key:
        return None

    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={outputsize}&apikey={api_key}"

    try:
        res = requests.get(url, timeout=10)
        data = res.json()

        if "values" not in data:
            return None

        df = pd.DataFrame(data["values"])
        df['time'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('time').reset_index(drop=True)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)

        return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"TwelveData exception for {symbol}: {e}")
        return None


def fetch_yfinance_forex(symbol: str, interval="1min", outputsize=100):
    yf_interval = YFINANCE_INTERVAL_MAP.get(interval, "1m")
    period = "1d" if yf_interval in ["1m", "5m"] else "5d"

    if symbol.upper() in ["XAU/USD", "XAUUSD", "GOLD"]:
        tickers_to_try = ["XAUUSD=X", "XAU-USD"]
    elif "/" in symbol:
        tickers_to_try = [symbol.replace("/", "") + "=X"]
    else:
        tickers_to_try = [symbol + "=X" if not symbol.endswith("=X") else symbol]

    for ticker in tickers_to_try:
        try:
            df = yf.download(ticker, period=period, interval=yf_interval, progress=False)
            if df is not None and not df.empty:
                df = df.reset_index()

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]

                time_col = "Datetime" if "Datetime" in df.columns else "Date"
                if time_col in df.columns:
                    df = df.rename(columns={
                        time_col: "time",
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume"
                    })
                    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
                    df = df.tail(outputsize).reset_index(drop=True)

                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = df[col].astype(float)

                    return df[['time', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            logger.error(f"Yahoo Finance error for {ticker}: {e}")

    return None


def get_data(symbol: str, interval="1min", outputsize=100):
    crypto_keywords = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "USDT"]
    is_crypto = any(coin in symbol.upper() for coin in crypto_keywords)

    if is_crypto:
        return fetch_binance_crypto(symbol, interval, outputsize)

    df = fetch_twelvedata_forex(symbol, interval, outputsize)

    if df is None or df.empty:
        df = fetch_yfinance_forex(symbol, interval, outputsize)

    return df
