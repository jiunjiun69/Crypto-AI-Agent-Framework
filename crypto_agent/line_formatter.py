# line_formatter.py
from typing import Dict


def build_prompt_for_llm(
    symbol: str,
    weekly_regime: str,
    weekly_row: Dict,
    daily_pattern: Dict,
) -> str:
    regime_zh = {
        "bull": "牛市",
        "bear": "熊市",
        "warning": "警戒區（可能由牛轉熊或震盪）",
        "neutral": "中性／盤整",
        "unknown": "資料不足，暫時無法判定",
    }.get(weekly_regime, weekly_regime)

    weekly_block = f"""
                    [週線級別]
                    - 最新一週收盤價：{weekly_row['close']:.2f}
                    - 週線 SMA50：{weekly_row['sma50']:.2f}
                    - 週線 SMA100：{weekly_row['sma100']:.2f}
                    - 週期判定：{regime_zh}
                    """

    if daily_pattern.get("status") == "ok":
        dp = daily_pattern
        daily_block = f"""
                    [日線量價]
                    - 昨日收盤價：{dp['close_prev']:.2f}
                    - 今日收盤價：{dp['close_last']:.2f}
                    - 價格方向：{"上漲" if dp["price_dir"]=="up" else "下跌" if dp["price_dir"]=="down" else "持平"}
                    - 今日成交量：{dp['vol_last']:.0f}
                    - 最近 {dp['avg_vol']:.0f} 平均量：約 {dp['avg_vol']:.0f}
                    - 量能狀態：{dp['vol_state']}（{dp['pattern']}）
                    """
                        else:
                            daily_block = "\n[日線量價]\n- 資料天數不足，暫不分析。\n"

                        prompt = f"""
                    你是一位偏保守、以風險控管為主的現貨加密貨幣顧問，幫使用者看 BTC 中長期形勢。

                    標的：{symbol}

                    {weekly_block}

                    {daily_block}

                    請用繁體中文，條列 3~5 點說明：
                    1. 目前屬於偏牛、偏熊或高風險警戒區？整體趨勢怎麼看？
                    2. 週線趨勢（牛/熊/警戒）與今日量價型態（例如放量下跌、縮量上漲）綜合起來，有什麼需要注意的？
                    3. 對於「現貨重倉」且不使用槓桿的投資人，現在比較像是：減倉、續抱觀望、還是可以分批佈局？請給出方向但不要給具體價格或 All in 建議。
                    4. 提醒 1~2 個可能的風險情境（例如之後如果跌破某種均線、或量能持續放大下跌要留意什麼）。

                    請避免精準預測價格，也不要建議槓桿與合約，專注在風險控管與節奏建議。
                    """

    return prompt


def format_line_message(symbol: str, llm_text: str) -> str:
    return f"【{symbol} 形勢分析（AI Agent）】\n\n{llm_text}"
