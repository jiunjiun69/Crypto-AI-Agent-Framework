"""
使用 LangGraph 將 Crypto AI Agent 的流程串成有狀態的 Graph。

State: AgentState
Nodes:
  - fetch_and_analyze       (Data + Analysis Agent)
  - build_prompt_node       (組 prompt)
  - call_llm_node           (Advice Agent 呼叫 LLM)
  - format_message_node     (Interface Agent：整理成 LINE 訊息)

邏輯仍然放在既有 modules，只用 LangGraph 做 orchestration。
"""

from typing import Dict, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END

from config import SYMBOL
from data_binance import get_daily_klines, get_weekly_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from line_formatter import build_prompt_for_llm, format_line_message
from llm_client import LLMClient
from observability import langfuse


# 1. 定義 Graph 的 State Schema
class AgentState(TypedDict, total=False):
    """
    LangGraph 在節點之間傳遞的狀態。
    """
    symbol: str

    # Analysis Agent 輸出
    weekly_regime: str
    weekly_row: Dict[str, float]
    daily_pattern: Dict[str, Any]

    # Advice / Interface Agent 用
    prompt: str
    summary: str
    message: str


# 2. 定義各個 Node（節點）

def fetch_and_analyze(state: AgentState) -> AgentState:
    """
    Data Agent + Analysis Agent：
    - 從 Binance 抓週線、日線 K 線
    - 計算週線 Regime（牛/熊/警戒/中性）
    - 計算日線量價 pattern
    """
    symbol = state.get("symbol") or SYMBOL

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

    return {
        "symbol": symbol,
        "weekly_regime": weekly_regime,
        "weekly_row": weekly_row,
        "daily_pattern": daily_pattern,
    }


def build_prompt_node(state: AgentState) -> AgentState:
    """
    將分析結果包成給 LLM 的 prompt。
    """
    symbol = state["symbol"]
    weekly_regime = state["weekly_regime"]
    weekly_row = state["weekly_row"]
    daily_pattern = state["daily_pattern"]

    prompt = build_prompt_for_llm(
        symbol=symbol,
        weekly_regime=weekly_regime,
        weekly_row=weekly_row,
        daily_pattern=daily_pattern,
    )

    # 把 prompt 放進 state，後面節點可以直接用
    state["prompt"] = prompt
    return state


def call_llm_node(state: AgentState) -> AgentState:
    """
    Advice Agent：
    - 用 LLM 讀取 prompt，吐出 summary（文字建議）
    - 順便在 Langfuse 打一個 span（如果有啟用）
    """
    symbol = state["symbol"]
    weekly_regime = state["weekly_regime"]
    prompt = state["prompt"]

    llm = LLMClient()

    span = None
    # --- Langfuse: 最小整合，只打 span，不玩 trace 物件 ---
    if langfuse is not None:
        try:
            # 這個 API 在新版 SDK 是存在的
            span = langfuse.start_span(
                name=f"llm.summarize.{symbol}.{weekly_regime}"
            )
        except Exception as e:
            print(f"[WARN] Langfuse span 建立失敗（略過）： {repr(e)}")
            span = None

    try:
        summary = llm.summarize(prompt)

        if span is not None:
            try:
                # 新版 end() 幾乎不吃參數，乖乖呼叫就好
                span.end()
            except Exception as e:
                print(f"[WARN] Langfuse span.end 失敗（略過）： {repr(e)}")

    except Exception as e:
        if span is not None:
            try:
                # 出錯一樣先把 span 收掉
                span.end()
            except Exception as e2:
                print(f"[WARN] Langfuse span.end(錯誤) 失敗（略過）： {repr(e2)}")
        # 把錯繼續往外丟給 LangGraph 處理
        raise

    # 關鍵：把 summary 存成 state["summary"]，後面 format_message_node 才找得到
    state["summary"] = summary
    return state


def format_message_node(state: AgentState) -> AgentState:
    """
    Interface Agent：把 LLM 回覆包裝成適合 LINE 顯示的訊息。
    """
    symbol = state["symbol"]
    summary = state["summary"]
    msg = format_line_message(symbol, summary)
    state["message"] = msg
    return state


# 3. 建立 LangGraph 的 StateGraph
def build_graph():
    """
    建一條：
      START → fetch_and_analyze → build_prompt → call_llm → format_message → END
    的有狀態 Graph。
    """
    builder = StateGraph(AgentState)

    # 加節點
    builder.add_node("fetch_and_analyze", fetch_and_analyze)
    builder.add_node("build_prompt", build_prompt_node)
    builder.add_node("call_llm", call_llm_node)
    builder.add_node("format_message", format_message_node)

    # 定義邊（流程）
    builder.add_edge(START, "fetch_and_analyze")
    builder.add_edge("fetch_and_analyze", "build_prompt")
    builder.add_edge("build_prompt", "call_llm")
    builder.add_edge("call_llm", "format_message")
    builder.add_edge("format_message", END)

    graph = builder.compile()
    return graph


def run_with_graph(symbol: str | None = None) -> str:
    """
    對外 API：
    - 丟進 symbol
    - 走 LangGraph 流程
    - 回傳最後的 message（可直接丟給 LINE）
    """
    from datetime import datetime

    symbol = symbol or SYMBOL
    graph = build_graph()

    print(f"[INFO] Start LangGraph analysis at {datetime.now()}")
    if langfuse is not None:
        print("[INFO] Langfuse 已啟用，host = http://localhost:3000")

    final_state: AgentState = graph.invoke({"symbol": symbol})
    return final_state["message"]


if __name__ == "__main__":
    msg = run_with_graph()
    print("\n===== 最終訊息預覽（LangGraph 版本）=====\n")
    print(msg)
    print("\n========================================\n")
