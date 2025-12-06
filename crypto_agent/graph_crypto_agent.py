"""
使用 LangGraph 將 Crypto AI Agent 的流程串成有狀態的 Graph。

State: AgentState
Nodes:
  - fetch_and_analyze       (Data + Analysis Agent)
  - build_prompt_node       (組 prompt)
  - call_llm_node           (Advice Agent 呼叫 LLM)
  - format_message_node     (Interface Agent：整理成 LINE 訊息)

讓邏輯保留在既有的 modules 裡，只用 LangGraph 做 orchestration，
並用 Langfuse 把整個 pipeline 的每一步都打進 trace/span。
"""

from typing import Dict, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END  # 核心 API

from config import SYMBOL
from data_binance import get_daily_klines, get_weekly_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from line_formatter import build_prompt_for_llm, format_line_message
from llm_client import LLMClient
from observability import langfuse


# =========================
# 1. 定義 Graph 的 State Schema
# =========================
class AgentState(TypedDict, total=False):
    """
    LangGraph 在節點之間傳遞的狀態。
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


# =========================
# 2. 定義各個 Node（節點）
# =========================

def _fetch_and_analyze_core(symbol: str):
    """
    把 fetch_and_analyze 的核心邏輯抽出來，方便在有 / 沒有 Langfuse span 時共用。
    """
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

    # 日線量價分析（analyze_daily_volume_price）
    daily_pattern = analyze_daily_volume_price(df_daily)

    return weekly_regime, weekly_row, daily_pattern


def fetch_and_analyze(state: AgentState) -> AgentState:
    """
    Data Agent + Analysis Agent：
    - 從 Binance 抓週線、日線 K 線
    - 計算週線 Regime（牛/熊/警戒/中性）
    - 計算日線量價 pattern

    並用 Langfuse 記一個 span：fetch_and_analyze
    """
    symbol = state.get("symbol") or SYMBOL

    # 有 / 沒有 Langfuse 都要能跑，所以用 try 包起來
    if langfuse is not None:
        try:
            # 這裡使用官方推薦的 API：start_as_current_observation
            # as_type="span" 代表這個 observation 是一個 span
            with langfuse.start_as_current_observation(
                as_type="span",
                name="fetch_and_analyze",
            ) as obs:
                # span input：這一步的輸入大致是 symbol
                obs.update(input={"symbol": symbol})

                weekly_regime, weekly_row, daily_pattern = _fetch_and_analyze_core(symbol)

                # span output：把分析結果精簡記錄
                obs.update(
                    output={
                        "weekly_regime": weekly_regime,
                        "weekly_row": weekly_row,
                        "daily_pattern": {
                            "status": daily_pattern.get("status"),
                            "pattern": daily_pattern.get("pattern"),
                            "vol_state": daily_pattern.get("vol_state"),
                        },
                    }
                )
        except Exception as e:
            print("[WARN] Langfuse span(fetch_and_analyze) 失敗（略過）：", repr(e))
            weekly_regime, weekly_row, daily_pattern = _fetch_and_analyze_core(symbol)
    else:
        weekly_regime, weekly_row, daily_pattern = _fetch_and_analyze_core(symbol)

    # 把結果塞回 state
    state["symbol"] = symbol
    state["weekly_regime"] = weekly_regime
    state["weekly_row"] = weekly_row
    state["daily_pattern"] = daily_pattern
    return state


def build_prompt_node(state: AgentState) -> AgentState:
    """
    將分析結果包成給 LLM 的 prompt。
    也在 Langfuse 中記一個 span：build_prompt
    """
    symbol = state["symbol"]
    weekly_regime = state["weekly_regime"]
    weekly_row = state["weekly_row"]
    daily_pattern = state["daily_pattern"]

    def _core() -> str:
        return build_prompt_for_llm(
            symbol=symbol,
            weekly_regime=weekly_regime,
            weekly_row=weekly_row,
            daily_pattern=daily_pattern,
        )

    if langfuse is not None:
        try:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="build_prompt",
            ) as obs:
                obs.update(
                    input={
                        "symbol": symbol,
                        "weekly_regime": weekly_regime,
                        "weekly_row": weekly_row,
                        "daily_pattern_brief": {
                            "status": daily_pattern.get("status"),
                            "pattern": daily_pattern.get("pattern"),
                        },
                    }
                )
                prompt = _core()
                obs.update(
                    output={
                        # 為了避免太長，只存 preview
                        "prompt_preview": prompt[:400],
                    }
                )
        except Exception as e:
            print("[WARN] Langfuse span(build_prompt) 失敗（略過）：", repr(e))
            prompt = _core()
    else:
        prompt = _core()

    state["prompt"] = prompt
    return state


def call_llm_node(state: AgentState) -> AgentState:
    """
    Advice Agent：
    - 用 LLM 讀取 prompt，吐出 summary（文字建議）
    - 在 Langfuse 打一個 span：call_llm
      （注意：llm_client.py 裡面原本自訂的 trace 也會存在，等於是雙層觀測）
    """
    symbol = state["symbol"]
    weekly_regime = state["weekly_regime"]
    prompt = state["prompt"]

    llm = LLMClient()

    def _core() -> str:
        return llm.summarize(prompt)

    if langfuse is not None:
        try:
            with langfuse.start_as_current_observation(
                as_type="span",
                name=f"call_llm.{symbol}.{weekly_regime}",
            ) as obs:
                obs.update(
                    input={
                        "symbol": symbol,
                        "weekly_regime": weekly_regime,
                        "prompt_preview": prompt[:400],
                    }
                )
                summary = _core()
                obs.update(
                    output={
                        "summary_preview": summary[:400],
                    }
                )
        except Exception as e:
            print("[WARN] Langfuse span(call_llm) 失敗（略過）：", repr(e))
            summary = _core()
    else:
        summary = _core()

    state["summary"] = summary
    return state


def format_message_node(state: AgentState) -> AgentState:
    """
    Interface Agent：把 LLM 回覆包裝成適合 LINE 顯示的訊息。
    同樣記一個 span：format_message
    """
    symbol = state["symbol"]
    summary = state["summary"]

    def _core() -> str:
        return format_line_message(symbol, summary)

    if langfuse is not None:
        try:
            with langfuse.start_as_current_observation(
                as_type="span",
                name="format_message",
            ) as obs:
                obs.update(
                    input={
                        "symbol": symbol,
                        "summary_preview": summary[:400],
                    }
                )
                msg = _core()
                obs.update(
                    output={
                        "message_preview": msg[:400],
                    }
                )
        except Exception as e:
            print("[WARN] Langfuse span(format_message) 失敗（略過）：", repr(e))
            msg = _core()
    else:
        msg = _core()

    state["message"] = msg
    return state


# =========================
# 3. 建立 LangGraph 的 StateGraph
# =========================

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

    如果有 Langfuse client，就用一個「根 span」把整條 pipeline 包起來，
    並且把 trace 的 input / output 也補齊。
    """
    import datetime as dt

    symbol = symbol or SYMBOL
    graph = build_graph()

    # 沒有 Langfuse：直接跑
    if langfuse is None:
        final_state: AgentState = graph.invoke({"symbol": symbol})
        return final_state["message"]

    # 有 Langfuse：用 start_as_current_observation 當 root span
    with langfuse.start_as_current_observation(
        as_type="span",
        name=f"crypto-agent.pipeline.{symbol}",
    ) as root_span:
        # 這裡更新 trace 的 input
        try:
            root_span.update_trace(
                input={
                    "symbol": symbol,
                    "started_at": dt.datetime.now().isoformat(),
                }
            )
        except Exception as e:
            print("[WARN] Langfuse root_span.update_trace(input) 失敗：", repr(e))

        # 真正執行 LangGraph
        final_state: AgentState = graph.invoke({"symbol": symbol})

        # 把整條 pipeline 的最終輸出塞回 trace output
        try:
            root_span.update_trace(
                output={
                    "symbol": symbol,
                    "weekly_regime": final_state.get("weekly_regime"),
                    "message": final_state.get("message", ""),
                }
            )
        except Exception as e:
            print("[WARN] Langfuse root_span.update_trace(output) 失敗：", repr(e))

    return final_state["message"]


if __name__ == "__main__":
    import datetime as dt

    print(f"[INFO] Start LangGraph analysis at {dt.datetime.now()}")
    msg = run_with_graph()
    print("\n===== 最終訊息預覽（LangGraph 版本）=====\n")
    print(msg)
    print("\n========================================\n")
