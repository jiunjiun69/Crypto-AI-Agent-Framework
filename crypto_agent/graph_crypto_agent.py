"""
LangGraph orchestration + Langfuse observability.

使用 LangGraph 將 Crypto AI Agent 的流程串成有狀態的 Graph。

State: AgentState
Nodes:
    - fetch_and_analyze span
    - analyst_weekly span + generation
    - analyst_daily span + generation
    - analyst_risk span + generation
    - investment_manager span
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

MANAGER_LLM_TEMPLATE = """\
你現在是一位資深的加密貨幣現貨投資經理（human-level in Chinese）。  
以下是三位分析師根據市場資料的結構化分析（包含 decision / summary / notes ），再加上系統的初步決策(preliminary decision)。

請你扮演「經理人」：
- 統整三位分析師的分析結果
- 不只是重述，而是清楚地解釋原因
- 給出一個一致的最終策略（BUY / HOLD / SELL）
- 並提出最重要的 2–3 個投資人應該注意的風險或行動建議
- 在開頭可以講到使用者意圖是何種，與給建議適不適合做意圖的事情
- 內容中可以再總結出分析師提到的週線、日線量價的趨勢內容，也可總結分析師提到的技術信號或指標，注意要使用繁體中文
- 使用者意圖是：{intent}（請先根據下方意圖轉換表變換過後再判斷），請特別根據此意圖給出判斷重點，提到的意圖也要轉換後再輸出到給出的內容中

意圖轉換表：
- general_advice：一般建議 / 目前看法
- bottom_fishing：想抄底
- risk_averse：怕回撤 / 想保守
- take_profit：想賣出 / 獲利了結
- heavy_position：想重倉 / 想加倉

**注意：**
🔹 不要輸出 JSON  
🔹 不要逐條列原始分析師文字 
🔹 不要使用 key:value 結構  
🔹 最後的結論段要明確指出總結與理由
🔹 使用自然、專業的中文，英文名詞或英文指標詞語等等都要盡量翻譯成繁體中文  

下面是可用資訊：

====== 使用者意圖 ======
{intent}

====== 週線趨勢分析師 ======
Decision: {weekly_decision}
Summary: {weekly_summary}
Notes: {weekly_notes}

====== 日線量價分析師 ======
Decision: {daily_decision}
Summary: {daily_summary}
Notes: {daily_notes}

====== 風險控管分析師 ======
Decision: {risk_decision}
Summary: {risk_summary}
Notes: {risk_notes}

====== 系統初步決策 ======
{prelim_decision}

---

請你撰寫一段「可直接給使用者看」的投資經理總結：

▶ 首先一句話給出你的**最終決策與最重要理由**  
▶ 接著用 2–3 句描述三位分析師的共識或分歧重點  
▶ 最後給出 2–3 個風險控制或行動建議（客觀中立）
"""


# ----------------------------
# Nodes
# ----------------------------

def fetch_and_analyze(state: AgentState) -> AgentState:
    symbol = state.get("symbol") or SYMBOL
    user_text = state.get("user_text") or ""
    ts = state.get("ts") or dt.datetime.now().isoformat()
    intent = state.get("intent") or _parse_intent(user_text)

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


def investment_manager_node(state: AgentState) -> AgentState:
    """
    合併 rule-based 決策融合 + LLM 投資經理總結的節點。
    - 先做 weighted vote 合併三位分析師
    - 再用 investment_manager LLM prompt 做最終總結（自然中文）
    """

    intent = state.get("intent", "general_advice")
    weights = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS["general_advice"])

    # 1) Rule-based 決策融合
    with SpanCtx("investment_manager", {"intent": intent, "weights": weights}) as span:

        # 順序固定讀三個分析師
        analysts_keys = [
            ("weekly", "analyst_weekly"),
            ("daily", "analyst_daily"),
            ("risk", "analyst_risk"),
        ]

        # collect & vote
        score = {"buy": 0.0, "hold": 0.0, "sell": 0.0}
        valid_results: List[AnalystResult] = []
        for role_name, key in analysts_keys:
            r = state.get(key, {})
            if isinstance(r, dict) and r.get("ok"):
                valid_results.append(r)
                d = r.get("decision")
                if d in score:
                    score[d] += weights.get(role_name, 1.0)

        if not valid_results:
            # 如果所有分析師都 fail，fallback
            fallback_summary = "市場資訊不足或模型解析失敗，請再試一次。"
            state["final_decision"] = {
                "final_decision": "hold",
                "summary": fallback_summary,
                "risk": ["無有效分析師輸出"],
            }
            span.update(output={"final_decision": state["final_decision"]})
            return state

        # 決策
        merged_decision = max(score, key=lambda k: score[k])

        # 初步彙整分析師 summary + risk
        merged_summary = "；".join([r.get("summary", "") for r in valid_results if r.get("summary")])
        merged_risk_list = []
        for r in valid_results:
            notes = r.get("notes")
            if notes:
                merged_risk_list.extend(notes if isinstance(notes, list) else [notes])

        preliminary = {
            "final_decision": merged_decision,
            "summary": merged_summary,
            "risk": merged_risk_list[:3],
        }

        # 更新 state，之後用於 LLM prompt
        state["final_decision"] = preliminary

        # 2) 用 LLM 做投資經理總結（自然中文）
        prompt = MANAGER_LLM_TEMPLATE.format(
            intent=intent,

            weekly_decision=state["analyst_weekly"].get("decision", ""),
            weekly_summary=state["analyst_weekly"].get("summary", ""),
            weekly_notes=state["analyst_weekly"].get("notes", ""),

            daily_decision=state["analyst_daily"].get("decision", ""),
            daily_summary=state["analyst_daily"].get("summary", ""),
            daily_notes=state["analyst_daily"].get("notes", ""),

            risk_decision=state["analyst_risk"].get("decision", ""),
            risk_summary=state["analyst_risk"].get("summary", ""),
            risk_notes=state["analyst_risk"].get("notes", ""),

            prelim_decision=merged_decision,
        )

        # 呼叫 LLM summary，並把回傳當作 summary_text
        with GenCtx("investment_manager.llm", {"prompt_preview": safe_preview(prompt, 2000)}) as gen:
            raw = chat_json(prompt)
            gen.update(output={"raw_preview": safe_preview(raw, 1200)})

        # LLM 有回文字就覆蓋掉 preliminary summary
        if isinstance(raw, str) and raw.strip():
            # 假設 LLM 回的是自然文字
            final_summary_text = raw.strip()
            final_state_dec = dict(preliminary)
            final_state_dec["summary"] = final_summary_text
            state["final_decision"] = final_state_dec
            span.update(output={"final_decision": state["final_decision"]})
        else:
            # fallback （若 LLM 回 dict 或 parse 不是文字, 就保留 preliminary）
            span.update(output={"final_decision_fallback": state["final_decision"]})

    return state


def format_message_node(state: AgentState) -> AgentState:
    # 你想在 Langfuse 看到哪些 input，就挑重要的放這裡
    span_input = {
        "symbol": state.get("symbol"),
        "intent": state.get("intent"),
        "final_decision": state.get("final_decision"),
    }

    with SpanCtx("format_message", span_input) as span:
        final = state["final_decision"]
        msg = format_line_message(state["symbol"], final)

        # 記錄輸出預覽
        span.update(output={"message_preview": safe_preview(msg, 300)})

        # ✅ 把 message 放回 state（不要只 return {"message": msg}）
        state["message"] = msg

    return state


def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("fetch_and_analyze", fetch_and_analyze)
    builder.add_node("multi_analyst", multi_analyst_node)
    builder.add_node("investment_manager", investment_manager_node)
    builder.add_node("format_message", format_message_node)

    builder.add_edge(START, "fetch_and_analyze")
    builder.add_edge("fetch_and_analyze", "multi_analyst")
    builder.add_edge("multi_analyst", "investment_manager")
    builder.add_edge("investment_manager", "format_message")
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
