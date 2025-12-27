from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from data_binance import get_daily_klines, get_weekly_klines
from indicators import analyze_daily_volume_price, classify_weekly_regime


def get_weekly_features(symbol: str) -> Dict[str, Any]:
    """Weekly trend context (regime + key moving averages)."""

    dfw = get_weekly_klines(symbol, limit=220)
    weekly_regime = classify_weekly_regime(dfw)

    return {
        "symbol": symbol,
        "weekly_regime": weekly_regime,  # {regime, close, sma50, sma100}
    }


def _serialize_candles(df: pd.DataFrame, n: int) -> List[Dict[str, Any]]:
    """
    Return last n candles as JSON-serializable dicts:
    [{date, open, high, low, close, volume}, ...]
    """
    df2 = df.sort_values("close_time").tail(n).copy()
    # Use date string for compactness (UTC)
    df2["date"] = df2["close_time"].dt.strftime("%Y-%m-%d")
    cols = ["date", "open", "high", "low", "close", "volume"]
    out = []
    for _, r in df2[cols].iterrows():
        out.append(
            {
                "date": str(r["date"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            }
        )
    return out


def get_daily_pattern_features(symbol: str, *, candle_rows: int = 35) -> Dict[str, Any]:
    """
    Daily features + provide daily_candles to satisfy analyst needs.
    `candle_rows` default 35 (enough for short-term context without huge prompt).
    """
    dfd = get_daily_klines(symbol, limit=max(220, candle_rows + 5))

    daily_pattern = analyze_daily_volume_price(dfd)
    daily_candles = _serialize_candles(dfd, candle_rows)

    return {
        "symbol": symbol,
        "daily_pattern": daily_pattern,
        "daily_candles": daily_candles,
    }
