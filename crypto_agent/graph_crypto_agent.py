"""
使用 LangGraph 將 Crypto AI Agent 的流程串成有狀態的 Graph。

State: AgentState
Nodes:
  - fetch_and_analyze       (Data + Analysis Agent)
  - build_prompt_node       (組 prompt)
  - call_llm_node           (Advice Agent 呼叫 LLM)
  - format_message_node     (Interface Agent：整理成 LINE 訊息)

讓邏輯保留在既有的 modules 裡，只用 LangGraph 做 orchestration。
"""

from typing import Dict, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END  # 核心 API 

from config import SYMBOL
from data_binance import get_daily_klines, get_weekly_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from line_formatter import build_prompt_for_llm, format_line_message
from llm_client import LLMClient


# 1. 定義 Graph 的 State Schema
class AgentState(TypedDict, total=False):
    """
    LangGraph 會在節點之間傳遞的狀態。
    用 TypedDict 只是幫型別檢查，實際 runtime 跟 dict 一樣。
    """
    symbol: str

    # Analysis Agent 輸出
    weekly_regime: str
    weekly_row: Dict[str, float]
    daily_pattern: Dict[str, Any]

    # Advice Agent / Interface Agent 用
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

    # 這裡拿到的是：regime, df_with_sma
    weekly_regime, df_weekly_with_sma = compute_weekly_regime(df_weekly)

    # 取最新一列，並轉成純 dict（裡面是標量）
    df_weekly_sorted = df_weekly_with_sma.sort_values("close_time")
    last = df_weekly_sorted.iloc[-1]

    weekly_row = {
        "close": float(last["close"]),
        "sma50": float(last["sma50"]),
        "sma100": float(last["sma100"]),
    }

    # 日線量價分析（你的 analyze_daily_volume_price）
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

    return {"prompt": prompt}


def call_llm_node(state: AgentState) -> AgentState:
    """
    Advice Agent：呼叫 LLM（OpenAI 或 Ollama）取得中文說明。
    """
    prompt = state["prompt"]
    llm = LLMClient()
    summary = llm.summarize(prompt)
    return {"summary": summary}


def format_message_node(state: AgentState) -> AgentState:
    """
    Interface Agent：把 LLM 回覆包裝成適合 LINE 顯示的訊息。
    """
    symbol = state["symbol"]
    summary = state["summary"]
    msg = format_line_message(symbol, summary)
    return {"message": msg}


# 3. 建立 LangGraph 的 StateGraph

def build_graph():
    """
    建一條：
      START → fetch_and_analyze → build_prompt_node → call_llm_node → format_message_node → END
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
    對外的簡單 API：
    - 丟進 symbol
    - 走 LangGraph 流程
    - 回傳最後的 message（可直接給 LINE 用）
    """
    symbol = symbol or SYMBOL
    graph = build_graph()
    # state 的初始值只需要傳 symbol，其餘會由節點慢慢補完
    final_state: AgentState = graph.invoke({"symbol": symbol})
    return final_state["message"]


if __name__ == "__main__":
    import datetime as dt

    print(f"[INFO] Start LangGraph analysis at {dt.datetime.now()}")
    msg = run_with_graph()
    print("\n===== 最終訊息預覽（LangGraph 版本）=====\n")
    print(msg)
    print("\n========================================\n")
