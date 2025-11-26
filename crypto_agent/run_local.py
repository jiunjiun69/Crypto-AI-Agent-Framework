"""
本地測試入口（LangGraph 版本）：

python run_local.py

會：
  - 建立 LangGraph flow
  - 執行一次「查詢現在 BTC 形勢」
  - 印出最後要給 LINE 的訊息內容
"""

import datetime as dt
from config import SYMBOL
from graph_crypto_agent import run_with_graph


def main():
    print(f"[INFO] Start LangGraph analysis at {dt.datetime.now()}")
    msg = run_with_graph(SYMBOL)

    print("\n===== 最終訊息預覽（之後會給 LINE ）=====\n")
    print(msg)
    print("\n========================================\n")


if __name__ == "__main__":
    main()
