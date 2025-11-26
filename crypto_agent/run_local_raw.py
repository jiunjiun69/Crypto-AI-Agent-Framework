# 舊版沒套用 langGraph 的版本
from datetime import datetime
from config import SYMBOL
from data_binance import get_weekly_klines, get_daily_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from llm_client import LLMClient
from line_formatter import build_prompt_for_llm, format_line_message


def main():
    print(f"[INFO] Start analysis at {datetime.now()}")

    # 1. 抓資料
    df_w = get_weekly_klines(symbol=SYMBOL, limit=200)
    df_d = get_daily_klines(symbol=SYMBOL, limit=400)

    # 2. 長期週線 regime
    regime, df_w_ma = compute_weekly_regime(df_w)
    last_week_row = df_w_ma.sort_values("close_time").iloc[-1]

    # 3. 日線量價分析
    daily_pattern = analyze_daily_volume_price(df_d)

    # 4. 準備給 LLM 的 prompt
    prompt = build_prompt_for_llm(
        symbol=SYMBOL,
        weekly_regime=regime,
        weekly_row=last_week_row,
        daily_pattern=daily_pattern,
    )

    # 5. 呼叫 LLM
    llm = LLMClient()
    summary = llm.summarize(prompt)

    # 6. 組合成訊息（之後可給 LINE）
    message = format_line_message(SYMBOL, summary)

    print("\n===== 最終訊息預覽（之後會給 LINE ）=====\n")
    print(message)
    print("\n======================================")


if __name__ == "__main__":
    main()
