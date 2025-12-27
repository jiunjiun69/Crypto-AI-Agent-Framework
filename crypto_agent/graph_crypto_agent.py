"""
LangGraph orchestration + Langfuse observability.

使用 LangGraph 將 Crypto AI Agent 的流程串成有狀態的 Graph。

State: AgentState
Nodes:
    - fetch_and_analyze span
    - analyst_weekly span + generation
    - analyst_daily span + generation
    - analyst_risk span + generation
    - manager_merge span
    - format_message span
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict, List, Optional, TypedDict

import pandas as pd

from langgraph.graph import StateGraph, START, END

from config import SYMBOL
from data_binance import get_daily_klines, get_weekly_klines
from indicators import compute_weekly_regime, analyze_daily_volume_price
from llm_client import chat_json
from observability import SpanCtx, GenCtx, safe_preview
from line_formatter import build_prompt_for_llm, format_line_message

# ----------------------------
# Intent Parsing
# ----------------------------
# Possible intents:
# (from user_text)
# ----------------------------
# 1) general_advice（一般建議）
# 2) bottom_fishing（抄底）
# 3) risk_averse（怕回撤 / 保守）
# 4) take_profit（想賣出 / 獲利了結）
# 5) heavy_position（重倉 / 加倉）
# ----------------------------

def _parse_intent(user_text: str) -> str:
    text = user_text.lower()

    if "抄底" in text or "底部" in text:
        return "bottom_fishing"
    if "怕回撤" in text or "怕回落" in text or "怕跌" in text:
        return "risk_averse"
    if "賣出" in text or "停利" in text or "想賣" in text:
        return "take_profit"
    if "重倉" in text or "加倉" in text or "多" in text:
        # avoid matching “做多” for general sentiment
        # so only heavy if explicitly 重倉/加倉
        return "heavy_position"
    # fallback general
    return "general_advice"

INTENT_WEIGHTS = {
    "general_advice": {"weekly": 1.0, "daily": 1.0, "risk": 1.0},
    "bottom_fishing": {"weekly": 0.5, "daily": 1.5, "risk": 1.0},
    "risk_averse": {"weekly": 0.5, "daily": 1.0, "risk": 1.5},
    "take_profit": {"weekly": 1.0, "daily": 0.8, "risk": 1.4},
    "heavy_position": {"weekly": 1.0, "daily": 1.2, "risk": 0.8},
}

# ----------------------------
# State Schema
# ----------------------------

class AnalystResult(TypedDict, total=False):
    ok: bool
    focus: str
    summary: str
    decision: str
    notes: str
    missing: List[str]


class AgentState(TypedDict, total=False):
    symbol: str
    user_text: str
    ts: str
    intent: str

    # analysis outputs
    weekly_row: Dict[str, float]
    weekly_regime: str
    daily_pattern: Dict[str, Any]
    daily_candles: List[Dict[str, Any]]

    # multi-analyst results
    analyst_weekly: AnalystResult
    analyst_daily: AnalystResult
    analyst_risk: AnalystResult

    # final
    final_decision: Dict[str, Any]
    message: str
    summary: str



# ----------------------------
# Helpers
# ----------------------------

def _serialize_candles(df: pd.DataFrame, n: int) -> List[Dict[str, Any]]:
    df2 = df.sort_values("close_time").tail(n).copy()
    df2["date"] = df2["close_time"].dt.strftime("%Y-%m-%d")
    out: List[Dict[str, Any]] = []
    for _, r in df2.iterrows():
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


# ----------------------------
# Prompt Schemas
# ----------------------------

BASE_PROMPT_TEMPLATE = """
[使用者提問]
{user_text}

[交易標的]
{symbol}

[週線資訊]
- regime: {weekly_regime}
- close: {close}
- sma50: {sma50}
- sma100: {sma100}

[日線概況]
- close_dir: {close_dir}
- vol_ratio: {vol_ratio}

[日線 candles (近 35 天)]
{daily_candles}

{special_instructions}
""".strip()


ANALYST_TEMPLATES = {
    "weekly": """
你是{role}。
請依週線資訊做判斷，請回傳嚴格 JSON：
{{
  "ok": true/false,
  "focus": "weekly",
  "decision": "...(buy/hold/sell)...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": "...",
  "missing": []
}}
""".strip(),
    "daily": """
你是{role}。
請依日線量價與 candles 做判斷，只回傳 JSON：
{{
  "ok": true/false,
  "focus": "daily",
  "decision": "...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": "...",
  "missing": []
}}
""".strip(),
    "risk": """
你是{role}。
請結合使用者提問與市場資訊提出風險控管 + 倉位 plan，只回傳 JSON：
{{
  "ok": true/false,
  "focus": "risk",
  "decision": "...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": "...",
  "missing": []
}}
""".strip(),
}


# ----------------------------
# Nodes
# ----------------------------

def fetch_and_analyze(state: AgentState) -> AgentState:
    symbol = state.get("symbol") or SYMBOL
    user_text = state.get("user_text") or ""
    ts = state.get("ts") or dt.datetime.now().isoformat()
    intent = state.get("intent") or user_text

    with SpanCtx("fetch_and_analyze", {"symbol": symbol, "user_text": user_text, "intent": intent, "ts": ts}) as span:
        df_daily = get_daily_klines(symbol, limit=220)
        df_weekly = get_weekly_klines(symbol, limit=220)

        regime, dfw = compute_weekly_regime(df_weekly)
        daily_pattern = analyze_daily_volume_price(df_daily)
        daily_candles = _serialize_candles(df_daily, 35)

        out = {
            "symbol": symbol,
            "user_text": user_text,
            "ts": ts,
            "intent": intent,
            "weekly_regime": regime,
            "weekly_row": {
                "close": dfw.iloc[-1]["close"],
                "sma50": dfw.iloc[-1]["sma50"],
                "sma100": dfw.iloc[-1]["sma100"],
            },
            "daily_pattern": daily_pattern,
            "daily_candles": daily_candles,
        }

        span.update(output={"weekly_regime": regime, "daily_pattern": daily_pattern})
        return out


def _run_analyst(prompt: str, name: str) -> AnalystResult:
    """
    Runs one analyst with trace:
    - SpanCtx for the overall analyst
    - GenCtx for the LLM invocation
    """

    result: AnalystResult = {}
    with SpanCtx(name, {"prompt_preview": safe_preview(prompt, 1200)}) as span:
        try:
            # generation span
            with GenCtx(f"{name}.llm", {"prompt_preview": safe_preview(prompt, 2000)}) as gen:
                raw = chat_json(prompt)
                # attach raw to gen span
                gen.update(output={"raw_preview": safe_preview(raw, 1200)})

            # if raw is dict-like or str
            result = raw if isinstance(raw, dict) else {}

            # attach result to span
            span.update(output={"result_preview": safe_preview(raw, 1200)})
        except Exception as e:
            # if error, log to span metadata
            span.update(
                output={"error": f"{type(e).__name__}: {str(e)[:200]}"},
                metadata={"status": "error"},
            )
            result = {"ok": False, "error": str(e)}

    return result



def multi_analyst_node(state: AgentState) -> AgentState:
    symbol = state["symbol"]
    user_text = state["user_text"]
    weekly_regime = state["weekly_regime"]
    weekly_row = state["weekly_row"]
    daily_pattern = state["daily_pattern"]
    daily_candles = state["daily_candles"]

    base_ctx = BASE_PROMPT_TEMPLATE.format(
        user_text=user_text,
        symbol=symbol,
        weekly_regime=weekly_regime,
        close=weekly_row["close"],
        sma50=weekly_row["sma50"],
        sma100=weekly_row["sma100"],
        close_dir=daily_pattern.get("close_dir"),
        vol_ratio=daily_pattern.get("vol_ratio"),
        daily_candles=json.dumps(daily_candles, ensure_ascii=False),
        special_instructions=f"使用者意圖: {state.get('intent')}。請特別根據此意圖給出判斷重點。"
    )

    analysts = {}

    analysts["analyst_weekly"] = _run_analyst(
        ANALYST_TEMPLATES["weekly"].format(role="週線趨勢分析師") + "\n\n" + base_ctx,
        "analyst_weekly",
    )

    analysts["analyst_daily"] = _run_analyst(
        ANALYST_TEMPLATES["daily"].format(role="日線量價分析師") + "\n\n" + base_ctx,
        "analyst_daily",
    )

    analysts["analyst_risk"] = _run_analyst(
        ANALYST_TEMPLATES["risk"].format(role="風險控管分析師") + "\n\n" + base_ctx,
        "analyst_risk",
    )

    state.update(analysts)
    return state


def manager_merge_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "general_advice")
    weights = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS["general_advice"])

    with SpanCtx(
        "manager_merge",
        { "intent": intent, "weights": weights },
    ) as span:

        results: List[AnalystResult] = [
            state.get("analyst_weekly", {}),
            state.get("analyst_daily", {}),
            state.get("analyst_risk", {}),
        ]

        # only ok
        valid = [r for r in results if isinstance(r, dict) and r.get("ok")]

        if not valid:
            summary = "市場資訊不足或模型解析失敗，請再試一次。"
            state["final_decision"] = {
                "final_decision": "hold",
                "summary": summary,
                "risk": ["無有效分析師輸出"],
            }
            span.update(output={"final_decision": state["final_decision"]})
            return state

        score = {"buy": 0.0, "hold": 0.0, "sell": 0.0}

        for role_name, r in zip(["weekly", "daily", "risk"], valid):
            d = r.get("decision")
            if d in score:
                score[d] += weights.get(role_name, 1.0)

        final_decision = max(score, key=lambda k: score[k])

        # summary + risk
        summary = "；".join([r.get("summary", "") for r in valid if r.get("summary")])
        risk_list = []
        for r in valid:
            notes = r.get("notes")
            if notes:
                risk_list.extend(notes if isinstance(notes, list) else [notes])

        state["final_decision"] = {
            "final_decision": final_decision,
            "summary": summary,
            "risk": risk_list[:3],
        }

        span.update(output={"final_decision": state["final_decision"]})

    return state


def format_message_node(state: AgentState) -> AgentState:
    final = state["final_decision"]
    msg = format_line_message(state["symbol"], final)
    return {"message": msg}


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("fetch_and_analyze", fetch_and_analyze)
    builder.add_node("multi_analyst", multi_analyst_node)
    builder.add_node("manager_merge", manager_merge_node)
    builder.add_node("format_message", format_message_node)

    builder.add_edge(START, "fetch_and_analyze")
    builder.add_edge("fetch_and_analyze", "multi_analyst")
    builder.add_edge("multi_analyst", "manager_merge")
    builder.add_edge("manager_merge", "format_message")
    builder.add_edge("format_message", END)

    return builder.compile()


def run_with_graph(symbol: str, user_text: str | None = None) -> str:
    symbol = symbol.upper()
    user_text = user_text or f"{symbol} 投資建議"
    ts = dt.datetime.now().isoformat()
    intent = _parse_intent(user_text)

    with SpanCtx(
        "crypto_agent.run",
        {"symbol": symbol, "intent": intent, "ts": ts},
    ) as root:

        graph = build_graph()
        final_state: AgentState = graph.invoke(
            {
                "symbol": symbol,
                "user_text": user_text,
                "intent": intent,
                "ts": ts,
            }
        )
        root.update(output={"final_message": final_state.get("message", "")})

    return final_state["message"]
