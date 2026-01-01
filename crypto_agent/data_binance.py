from __future__ import annotations

from typing import Literal

import pandas as pd
import requests

"""
參閱 Binance API 文件：
    https://github.com/binance/binance-public-data?tab=readme-ov-file#klines
    https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data

1. 公共現貨 Klines (Candlestick) 資料端點 (無需 API Key 即可使用此端點取得 Klines 資料)
    https://api.binance.com/api/v3/klines


2. Swagger UI (/api/v3/klines):
    https://binance.github.io/binance-api-swagger/

3. 回傳格式欄位說明（目前回傳只有照順序排序，不會顯示key資訊）：
    Open time                       : 開盤時間
    Open                            : 開盤價
    High                            : 最高價
    Low                             : 最低價
    Close                           : 收盤價
    Volume                          : 成交量
    Close time                      : 收盤時間
    Quote asset volume              : 交易量
    Number of trades                : 成交筆數
    Taker buy base asset volume     : 買進基礎資產成交量
    Taker buy quote asset volume    : 買入報價資產成交量
    Ignore                          : 忽略
"""

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
    print(f"[INFO] Fetching klines from Binance: {params}")
    r = requests.get(BINANCE_SPOT_KLINES_URL, params=params, timeout=30)
    print(f"[INFO] Binance response status: {r}")
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
