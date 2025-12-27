from __future__ import annotations

from typing import Literal

import pandas as pd
import requests


BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"


def _get_klines(
    symbol: str,
    interval: Literal[
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w",
        "1M",
    ],
    limit: int,
) -> pd.DataFrame:
    """
    Fetch klines from Binance public spot endpoint (no API key needed).

    Response format:
    [
      [
        0 open time,
        1 open,
        2 high,
        3 low,
        4 close,
        5 volume,
        6 close time,
        7 quote asset volume,
        8 number of trades,
        9 taker buy base asset volume,
        10 taker buy quote asset volume,
        11 ignore
      ],
      ...
    ]
    """
    symbol = symbol.upper().strip()
    params = {"symbol": symbol, "interval": interval, "limit": int(limit)}
    r = requests.get(BINANCE_SPOT_KLINES_URL, params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()

    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "number_of_trades",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
        "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)

    # types
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def get_daily_klines(symbol: str, limit: int = 200) -> pd.DataFrame:
    return _get_klines(symbol, "1d", limit)


def get_weekly_klines(symbol: str, limit: int = 200) -> pd.DataFrame:
    return _get_klines(symbol, "1w", limit)
