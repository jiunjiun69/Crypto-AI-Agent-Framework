"""
核心 Use Case：不依賴 LangGraph 的版本
之後 LangGraph 的節點會直接呼叫這裡的邏輯，
也方便在其他地方（例如未來 LINE Webhook / FastAPI）重用。
"""

import datetime as dt

from config import SYMBOL
from data_binance import get_daily_klines, get_weekly_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from line_formatter import build_prompt_for_llm, format_line_message
from llm_client import LLMClient


def analyze_market(symbol: str | None = None) -> str:
    symbol = symbol or SYMBOL

    df_daily = get_daily_klines(symbol)
    df_weekly = get_weekly_klines(symbol)

    weekly_regime, df_weekly_with_sma = compute_weekly_regime(df_weekly)

    df_weekly_sorted = df_weekly_with_sma.sort_values("close_time")
    last = df_weekly_sorted.iloc[-1]
    weekly_row = {
        "close": float(last["close"]),
        "sma50": float(last["sma50"]),
        "sma100": float(last["sma100"]),
    }

    daily_pattern = analyze_daily_volume_price(df_daily)

    prompt = build_prompt_for_llm(
        symbol=symbol,
        weekly_regime=weekly_regime,
        weekly_row=weekly_row,
        daily_pattern=daily_pattern,
    )

    llm = LLMClient()
    summary = llm.summarize(prompt)

    message = format_line_message(symbol, summary)
    return message


if __name__ == "__main__":
    print(f"[INFO] Start analysis at {dt.datetime.now()}")
    msg = analyze_market()
    print("\n===== 最終訊息預覽（service.py 單獨執行）=====\n")
    print(msg)
    print("\n==========================================\n")
