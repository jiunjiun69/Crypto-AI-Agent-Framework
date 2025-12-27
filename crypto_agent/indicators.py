from __future__ import annotations
import pandas as pd

def compute_weekly_regime(df_weekly: pd.DataFrame):
    """
    Weekly regime by SMA50/SMA100 (weekly).
    Returns:
      regime: str
      df: df with sma50/sma100 columns
    """
    df = df_weekly.copy()
    if "close" not in df.columns:
        raise ValueError("weekly df must contain 'close'")

    df = df.sort_values("close_time").reset_index(drop=True)
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma100"] = df["close"].rolling(100).mean()

    last = df.iloc[-1]
    sma50 = last["sma50"]
    sma100 = last["sma100"]

    if pd.isna(sma50) or pd.isna(sma100):
        regime = "unknown"
    elif sma50 > sma100:
        regime = "bull"
    elif sma50 < sma100:
        regime = "bear"
    else:
        regime = "sideways"

    return regime, df


# Backward-compatible helper: some modules previously imported this name.
def classify_weekly_regime(df_weekly: pd.DataFrame) -> dict:
    regime, df = compute_weekly_regime(df_weekly)
    if len(df) == 0:
        return {"regime": "unknown", "close": None, "sma50": None, "sma100": None}

    last = df.sort_values("close_time").iloc[-1]
    return {
        "regime": regime,
        "close": float(last["close"]) if pd.notna(last["close"]) else None,
        "sma50": float(last["sma50"]) if pd.notna(last["sma50"]) else None,
        "sma100": float(last["sma100"]) if pd.notna(last["sma100"]) else None,
    }


def analyze_daily_volume_price(df_daily: pd.DataFrame):
    """
    Simple daily pattern features:
      - close up/down vs prev day
      - volume vs 20d avg ratio
    """
    df = df_daily.sort_values("close_time").reset_index(drop=True)

    if len(df) < 2:
        return {"ok": False, "reason": "not enough daily candles (need >=2)"}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close_last = float(last["close"])
    close_prev = float(prev["close"])
    close_change = close_last - close_prev
    close_dir = "up" if close_change > 0 else "down" if close_change < 0 else "flat"

    # volume ratio vs 20d mean
    df["vol20"] = df["volume"].rolling(20).mean()
    vol20 = float(df.iloc[-1]["vol20"]) if pd.notna(df.iloc[-1]["vol20"]) else None
    vol_last = float(last["volume"])

    if vol20 and vol20 > 0:
        vol_ratio = vol_last / vol20
    else:
        vol_ratio = None

    return {
        "ok": True,
        "close_dir": close_dir,
        "close_last": close_last,
        "close_prev": close_prev,
        "close_change": close_change,
        "vol_last": vol_last,
        "vol20": vol20,
        "vol_ratio": vol_ratio,
    }
