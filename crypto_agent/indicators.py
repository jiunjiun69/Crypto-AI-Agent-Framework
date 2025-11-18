# indicators.py
import pandas as pd
import numpy as np
from config import (
    WEEKLY_SMA_SHORT,
    WEEKLY_SMA_LONG,
    VOLUME_LOOKBACK,
    VOLUME_SPIKE_FACTOR,
    VOLUME_DRY_FACTOR,
)


def compute_weekly_regime(df_weekly: pd.DataFrame):
    """
    根據週線 close & SMA50/100 判定牛/熊/警戒/中性.

    規則：
      - bull:
          最近3週 close > sma50，且最後一週 close > sma50 * 1.02
          且 sma50 > sma100
      - bear:
          最近2週 close < sma50，且最後一週 close < sma50 * 0.98
          且 close < sma100
      - warning:
          剛跌破 sma50 或 收盤在 sma50 上下 1% 內震盪
      - neutral:
          其他
    """
    df = df_weekly.copy().sort_values("close_time")
    df["sma50"] = df["close"].rolling(WEEKLY_SMA_SHORT).mean()
    df["sma100"] = df["close"].rolling(WEEKLY_SMA_LONG).mean()

    if len(df) < WEEKLY_SMA_LONG + 5:
        return "unknown", df

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if np.isnan(last["sma50"]) or np.isnan(last["sma100"]):
        return "unknown", df

    last3 = df.tail(3)
    last2 = df.tail(2)

    close_last = last["close"]
    sma50_last = last["sma50"]
    sma100_last = last["sma100"]
    close_prev = prev["close"]
    sma50_prev = prev["sma50"]

    # bear
    last2_below_sma50 = (last2["close"] < last2["sma50"]).all()
    if last2_below_sma50 and close_last < sma50_last * 0.98 and close_last < sma100_last:
        regime = "bear"

    # bull
    elif (
        (last3["close"] > last3["sma50"]).all()
        and close_last > sma50_last * 1.02
        and sma50_last > sma100_last
    ):
        regime = "bull"

    else:
        just_broke_down = (close_last < sma50_last) and (close_prev >= sma50_prev)
        around_sma = abs(close_last - sma50_last) / sma50_last < 0.01
        if just_broke_down or around_sma:
            regime = "warning"
        else:
            regime = "neutral"

    return regime, df


def analyze_daily_volume_price(df_daily: pd.DataFrame) -> dict:
    """
    分析最近一日的量價結構，給 LLM 當參考。

    判斷重點：
      - 價格漲跌（收盤 vs 前一日）
      - 今天成交量 vs 近 N 日平均量
      - 放量上漲 / 放量下跌 / 縮量上漲 / 縮量下跌
    """
    df = df_daily.copy().sort_values("close_time")
    if len(df) < VOLUME_LOOKBACK + 2:
        return {"status": "insufficient_data"}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close_last = last["close"]
    close_prev = prev["close"]
    vol_last = last["volume"]

    # 計算平均量（排除今天）
    recent_hist = df.iloc[-(VOLUME_LOOKBACK + 1):-1]
    avg_vol = recent_hist["volume"].mean()

    price_change = close_last - close_prev
    price_dir = "up" if price_change > 0 else "down" if price_change < 0 else "flat"

    vol_ratio = vol_last / avg_vol if avg_vol > 0 else np.nan

    if np.isnan(vol_ratio):
        vol_state = "unknown"
    elif vol_ratio >= VOLUME_SPIKE_FACTOR:
        vol_state = "high"  # 放量
    elif vol_ratio <= VOLUME_DRY_FACTOR:
        vol_state = "low"   # 縮量
    else:
        vol_state = "normal"

    # 組合語意
    pattern = "unknown"
    if price_dir == "up" and vol_state == "high":
        pattern = "放量上漲"
    elif price_dir == "up" and vol_state == "low":
        pattern = "縮量上漲"
    elif price_dir == "down" and vol_state == "high":
        pattern = "放量下跌"
    elif price_dir == "down" and vol_state == "low":
        pattern = "縮量下跌"
    elif price_dir == "flat" and vol_state == "high":
        pattern = "放量橫盤"
    elif price_dir == "flat" and vol_state == "low":
        pattern = "縮量橫盤"
    else:
        pattern = "量價變化普通"

    return {
        "status": "ok",
        "close_last": close_last,
        "close_prev": close_prev,
        "price_dir": price_dir,
        "vol_last": vol_last,
        "avg_vol": avg_vol,
        "vol_ratio": vol_ratio,
        "vol_state": vol_state,
        "pattern": pattern,
    }
