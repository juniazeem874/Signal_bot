import requests
import pandas as pd
import yfinance as yf
import logging
import config

logger = logging.getLogger(__name__)

BINANCE_INTERVAL_MAP = {"1m": "1m", "1min": "1m", "15m": "15m", "15min": "15m"}
BYBIT_INTERVAL_MAP = {"1m": "1", "1min": "1", "15m": "15", "15min": "15"}
YFINANCE_INTERVAL_MAP = {"1m": "1m", "1min": "1m", "15m": "15m", "15min": "15m"}
TWELVEDATA_INTERVAL_MAP = {"1m": "1min", "1min": "1min", "15m": "15min", "15min": "15min"}


def normalize_forex_symbol(symbol: str) -> str:
    """'XAUUSD' -> 'XAU/USD', 'EURUSD' -> 'EUR/USD'. Leaves already-slashed
    symbols and anything non-6-letter alone."""
    s = symbol.upper().strip()
    if "/" in s or len(s) != 6:
        return s
    return f"{s[:3]}/{s[3:]}"


def fetch_binance_crypto(symbol: str, interval="1m", outputsize=100):
    try:
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        if clean_symbol.endswith("USD") and not clean_symbol.endswith("USDT"):
            clean_symbol += "T"
        if not (clean_symbol.endswith("USDT") or clean_symbol.endswith("BUSD")):
            clean_symbol += "USDT"

        b_interval = BINANCE_INTERVAL_MAP.get(interval, "1m")
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval={b_interval}&limit={outputsize}"

        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            # Common on cloud hosts (Railway/Render/AWS/GCP IPs): Binance
            # returns 451/403 "Service unavailable from a restricted location".
            logger.error(f"Binance HTTP {res.status_code} for {clean_symbol}: {res.text[:200]}")
            return None

        data = res.json()
        if not isinstance(data, list) or len(data) == 0:
            logger.error(f"Binance returned no candle data for {clean_symbol}: {data}")
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


def fetch_bybit_crypto(symbol: str, interval="1m", outputsize=100):
    """Bybit's public spot kline endpoint — no auth needed, and generally not
    subject to the same geo/cloud-IP blocking Binance applies."""
    try:
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        if clean_symbol.endswith("USD") and not clean_symbol.endswith("USDT"):
            clean_symbol += "T"
        if not (clean_symbol.endswith("USDT") or clean_symbol.endswith("USDC")):
            clean_symbol += "USDT"

        b_interval = BYBIT_INTERVAL_MAP.get(interval, "1")
        url = (
            f"https://api.bybit.com/v5/market/kline?category=spot"
            f"&symbol={clean_symbol}&interval={b_interval}&limit={outputsize}"
        )

        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            logger.error(f"Bybit HTTP {res.status_code} for {clean_symbol}: {res.text[:200]}")
            return None

        data = res.json()
        if data.get("retCode") != 0:
            logger.error(f"Bybit API error for {clean_symbol}: {data.get('retMsg')}")
            return None

        rows = data.get("result", {}).get("list", [])
        if not rows:
            logger.error(f"Bybit returned no candle data for {clean_symbol}")
            return None

        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
        df['time'] = pd.to_datetime(df['open_time'].astype(float), unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        # Bybit returns newest-first — sort ascending like Binance/TwelveData.
        df = df.sort_values('time').reset_index(drop=True)
        return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"Bybit fetch error for {symbol}: {e}")
        return None


def fetch_twelvedata_forex(symbol: str, interval="1min", outputsize=100):
    try:
        api_key = getattr(config, "TWELVEDATA_API_KEY", "")
        if not api_key:
            logger.warning("TWELVEDATA_API_KEY not set — skipping TwelveData.")
            return None

        td_interval = TWELVEDATA_INTERVAL_MAP.get(interval, "1min")
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={td_interval}&outputsize={outputsize}&apikey={api_key}"

        res = requests.get(url, timeout=10)
        data = res.json()

        if "values" not in data:
            logger.error(f"TwelveData no data for {symbol}: {data}")
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


def fetch_yfinance_forex(symbol: str, interval="1m", outputsize=100):
    try:
        yf_interval = YFINANCE_INTERVAL_MAP.get(interval, "1m")
        period = "1d" if yf_interval in ["1m", "5m"] else "5d"

        if symbol.upper() in ["XAU/USD", "XAUUSD", "GOLD"]:
            tickers_to_try = ["XAUUSD=X", "XAU-USD", "GC=F"]
        elif "/" in symbol:
            tickers_to_try = [symbol.replace("/", "") + "=X"]
        else:
            tickers_to_try = [symbol + "=X" if not symbol.endswith("=X") else symbol]

        for ticker in tickers_to_try:
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
            else:
                logger.warning(f"Yahoo Finance empty for ticker {ticker} (interval={yf_interval})")
    except Exception as e:
        logger.error(f"Yahoo Finance error for {symbol}: {e}")

    return None


def fetch_yfinance_crypto(symbol: str, interval="1m", outputsize=100):
    """Fallback crypto source when Binance is unreachable/blocked (common on
    cloud hosts like Railway, which Binance sometimes geo/IP-blocks)."""
    try:
        yf_interval = YFINANCE_INTERVAL_MAP.get(interval, "1m")
        period = "1d" if yf_interval in ["1m", "5m"] else "5d"

        clean = symbol.upper().replace("/", "").replace("-", "")
        for suffix in ["USDT", "BUSD", "USD"]:
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
                break
        ticker = f"{clean}-USD"

        df = yf.download(ticker, period=period, interval=yf_interval, progress=False)
        if df is None or df.empty:
            logger.warning(f"Yahoo Finance empty for crypto ticker {ticker}")
            return None

        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        time_col = "Datetime" if "Datetime" in df.columns else "Date"
        if time_col not in df.columns:
            return None

        df = df.rename(columns={
            time_col: "time", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume"
        })
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
        df = df.tail(outputsize).reset_index(drop=True)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = df[col].astype(float)

        return df[['time', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"Yahoo Finance crypto error for {symbol}: {e}")
        return None


def fetch_tf_data(symbol: str, interval: str):
    crypto_keywords = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "USDT"]
    is_crypto = any(coin in symbol.upper() for coin in crypto_keywords)

    if is_crypto:
        df = fetch_binance_crypto(symbol, interval)
        if df is None or df.empty:
            logger.warning(f"Binance failed for {symbol} — trying Bybit.")
            df = fetch_bybit_crypto(symbol, interval)
        if df is None or df.empty:
            logger.warning(f"Bybit failed for {symbol} — falling back to Yahoo Finance.")
            df = fetch_yfinance_crypto(symbol, interval)
        return df

    norm_symbol = normalize_forex_symbol(symbol)
    df = fetch_twelvedata_forex(norm_symbol, interval)
    if df is None or df.empty:
        df = fetch_yfinance_forex(norm_symbol, interval)

    return df


def get_data(symbol: str):
    """
    Main router function.
    STRICTLY GUARANTEES returning exactly 2 elements: (entry_df, trend_df).
    """
    try:
        entry_df = fetch_tf_data(symbol, interval="1m")
        trend_df = fetch_tf_data(symbol, interval="15m")
        if entry_df is None or trend_df is None:
            logger.error(
                f"get_data({symbol}) failed — entry_df is None: {entry_df is None}, "
                f"trend_df is None: {trend_df is None}. Check the logs above for the "
                f"specific source error (Binance/TwelveData/Yahoo)."
            )
        return entry_df, trend_df
    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return None, None
