from binance.client import Client
import pandas as pd
from typing import Optional
from config import BINANCE_API_KEY, BINANCE_API_SECRET, SYMBOL


def _create_client() -> Client:
    api_key = BINANCE_API_KEY or None
    api_secret = BINANCE_API_SECRET or None
    return Client(api_key=api_key, api_secret=api_secret)


def get_klines(
    symbol: Optional[str] = None,
    interval: str = "1d",
    limit: int = 500,
) -> pd.DataFrame:
    """
    從 Binance 抓 K 線資料，轉成 DataFrame.
    """
    symbol = symbol or SYMBOL
    client = _create_client()
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    df = pd.DataFrame(
        klines,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "num_trades",
            "taker_base_vol", "taker_quote_vol", "ignore",
        ],
    )

    # 型別轉換
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

    return df


def get_daily_klines(symbol: Optional[str] = None, limit: int = 400) -> pd.DataFrame:
    return get_klines(symbol=symbol, interval="1d", limit=limit)


def get_weekly_klines(symbol: Optional[str] = None, limit: int = 200) -> pd.DataFrame:
    return get_klines(symbol=symbol, interval="1w", limit=limit)
