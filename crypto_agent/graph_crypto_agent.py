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
from llm_client import chat_json, chat_text
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

INTENT_LABELS = {
    "general_advice": "一般建議 / 想了解目前形勢",
    "bottom_fishing": "想抄底",
    "risk_averse": "怕回撤 / 想保守",
    "take_profit": "想賣出 / 獲利了結",
    "heavy_position": "想重倉 / 想加倉",
}



# ----------------------------
# State Schema
# ----------------------------

class AnalystResult(TypedDict, total=False):
    ok: bool
    focus: str
    summary: str
    decision: str
    notes: List[str]
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

def _protect_actions(t: str) -> str:
    return (t.replace("BUY", "__ACTION_BUY__")
             .replace("HOLD", "__ACTION_HOLD__")
             .replace("SELL", "__ACTION_SELL__"))

def _restore_actions(t: str) -> str:
    return (t.replace("__ACTION_BUY__", "BUY")
             .replace("__ACTION_HOLD__", "HOLD")
             .replace("__ACTION_SELL__", "SELL"))
    
def _clean_for_line(text: str) -> str:
    t = (text or "").strip()
    t = _protect_actions(t)

    # 1) 去掉常見 Markdown 符號
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)  # ### 標題
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"^[\*\-\u2022]\s+", "", t, flags=re.MULTILINE)  # * - • 開頭
    t = t.replace("`", "")

    # 2) 英文詞彙簡單翻譯（避免混英）
    replacements = {
        "selling signal": "賣出訊號",
        "buying signal": "買入訊號",
        "selling pressure": "賣壓",
        "buying pressure": "買盤",
        "stop loss": "止損",
        "take profit": "停利",
        "uptrend Continues": "上升趨勢持續",
        "uptrend Continued": "上升趨勢持續",
        "uptrend Continue": "上升趨勢持續",
        "downtrend Continues": "下降趨勢持續",
        "downtrend Continued": "下降趨勢持續",
        "downtrend Continue": "下降趨勢持續",
        "uptrend": "上升趨勢",
        "downtrend": "下降趨勢",
        "sideways trend": "盤整趨勢",
        "sideways": "盤整",
        "volumes": "成交量",
        "volume": "成交量",
        "moving averages": "移動平均線",
        "moving average": "移動平均線",
        "simple moving averages": "簡單移動平均線",
        "simple moving average": "簡單移動平均線",
        "exponential moving averages": "指數移動平均線",
        "exponential moving average": "指數移動平均線",
        "relative strength indices": "相對強弱指標",
        "relative strength index": "相對強弱指標",
        "risk management": "風險管理",
        "risk control": "風險控管",
        "position sizing": "倉位大小",
        "portfolio": "投資組合",
        "holdings": "持倉",
        "holding": "持有",

        # 補強：單字型態
        "selling": "賣出",
        "sell": "賣出",
        "buying": "買入",
        "buy": "買入",
        "bullish": "多頭",
        "bearish": "空頭",
        "volatility": "波動",
        "signal": "訊號",
        "order": "訂單",
        "price": "價格",
        "risk": "風險",
        "reward": "報酬",
        "entry": "進場",
        "exit": "出場",
        "stop": "停損",
        "limit": "限價",
        "market": "市價",
        "position": "倉位",
        "volume": "成交量",
        "trend": "趨勢",
        "resistance": "阻力",
        "support": "支撐",
        "levels": "價位",
        "level": "價位",
        "indicators": "指標",
        "indicator": "指標",
        "analysis": "分析",
        "analyst": "分析師",
        "decision": "決策",
        "summary": "總結",
        "confidence": "信心",
        "notes": "備註",
        "firstly": "首先",
        "secondly": "其次",
        "thirdly": "第三",
        "finally": "最後",
        "regime": "趨勢",
        "candles": "K線",
        "candle": "K線",
        "Ratio": "比率",
        "ratio": "比率",
        "movement": "走勢",
        "bullishness": "多頭",
        "bearishness": "空頭",
        "momentum": "動能",
        "volatility": "波動",
        "bullish": "多頭",
        "bearish": "空頭",
    }
    lower = t.lower()
    for k, v in replacements.items():
        # 粗略替換：同時處理原大小寫
        t = re.sub(re.escape(k), v, t, flags=re.IGNORECASE)

    # 3) 收斂空行
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    t = _restore_actions(t)
    return t

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
•	「所有文字請用繁體中文，禁止英文單字」
•	「notes 必須是陣列（list of strings），每個元素 20 字以內」
•	可以提到技術指標與關鍵價格位，但不要提到「分析師」「根據使用者輸入資料」等字眼
請依週線資訊做判斷，請回傳嚴格 JSON：
{{
  "ok": true/false,
  "focus": "weekly",
  "decision": "...(buy/hold/sell)...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": [],
  "missing": []
}}
""".strip(),
    "daily": """
你是{role}。
•	「所有文字請用繁體中文，禁止英文單字」
•	「notes 必須是陣列（list of strings），每個元素 20 字以內」
•	可以提到技術指標與關鍵價格位，但不要提到「分析師」「根據使用者輸入資料」等字眼
請依日線量價與 candles 做判斷，只回傳 JSON：
{{
  "ok": true/false,
  "focus": "daily",
  "decision": "...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": [],
  "missing": []
}}
""".strip(),
    "risk": """
你是{role}。
•	「所有文字請用繁體中文，禁止英文單字」
•	「notes 必須是陣列（list of strings），每個元素 20 字以內」
•	可以提到技術指標與關鍵價格位，但不要提到「分析師」「根據使用者輸入資料」等字眼
請結合使用者提問與市場資訊提出風險控管 + 倉位 plan，只回傳 JSON：
{{
  "ok": true/false,
  "focus": "risk",
  "decision": "...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {{"support":"...", "resistance":"..."}},
  "notes": [],
  "missing": []
}}
""".strip(),
}

MANAGER_LLM_TEMPLATE = """\
你是一位資深加密貨幣現貨投資經理，請用「給一般投資人看的繁體中文」輸出結論。

重要規則（務必遵守）：
- 可以提到技術指標與關鍵價格位，但不要提到「分析師」「三位分析師」「根據使用者輸入資料」「系統初步決策」等字眼
- 不要使用 Markdown（不要出現 ###、**、*、- 這類符號）
- 不要混用英文：把 holding / selling pressure / order / price 等換成繁體中文
- 內容不得自相矛盾：你的最終策略必須與下方「最終策略」一致
- 文字要精簡、專業、可直接貼到 LINE
- 除了 BUY/HOLD/SELL 之外，禁止任何英文單字（包含 bullish、signal、volatility 等）
- 禁止使用「總結」「最終策略判斷」「主要共識」這類報告腔標題字眼

使用者原始提問：
{user_text}

推斷的行為意圖（自然語言）：
{intent_label}

最終策略（不可更改）：
{final_decision}  （只會是 BUY / HOLD / SELL）

市場觀點素材（供你整理，不要照抄）：

週線觀點：
決策: {weekly_decision}
重點: {weekly_summary}
補充: {weekly_notes}

日線量價觀點：
決策: {daily_decision}
重點: {daily_summary}
補充: {daily_notes}

風險控管觀點：
決策: {risk_decision}
重點: {risk_summary}
補充: {risk_notes}

請輸出三段文字（用換行分隔即可，不要列點符號）：

第一段：一句話給出最終策略與最重要理由（要明確寫出 BUY/HOLD/SELL）
第二段：用 2–3 句把週線與日線量價的關鍵訊號統整成「為何支持這個策略」
第三段：給 2–3 個具體可執行的風險控管/行動建議（需與最終策略一致）
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
                raw = chat_json(prompt, temperature=0)
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

    intent = state.get("intent", "general_advice")
    intent_label = INTENT_LABELS.get(intent, intent)

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
        special_instructions=f"使用者意圖: {intent_label}。請特別根據此意圖給出判斷重點。"
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
        risk_notes = state.get("analyst_risk", {}).get("notes", [])
        if isinstance(risk_notes, str):
            risk_notes = [risk_notes]
        elif not isinstance(risk_notes, list):
            risk_notes = []

        preliminary = {
            "final_decision": merged_decision,
            "summary": merged_summary,
            "risk": risk_notes[:3],
        }

        # 更新 state，之後用於 LLM prompt
        state["final_decision"] = preliminary

        # 2) 用 LLM 做投資經理總結（自然中文）
        intent_label = INTENT_LABELS.get(intent, intent)

        prompt = MANAGER_LLM_TEMPLATE.format(
            user_text=state.get("user_text", ""),
            intent_label=intent_label,
            final_decision=merged_decision,   # 鎖定最終策略

            weekly_decision=state.get("analyst_weekly", {}).get("decision", ""),
            weekly_summary=state.get("analyst_weekly", {}).get("summary", ""),
            weekly_notes=state.get("analyst_weekly", {}).get("notes", ""),

            daily_decision=state.get("analyst_daily", {}).get("decision", ""),
            daily_summary=state.get("analyst_daily", {}).get("summary", ""),
            daily_notes=state.get("analyst_daily", {}).get("notes", ""),

            risk_decision=state.get("analyst_risk", {}).get("decision", ""),
            risk_summary=state.get("analyst_risk", {}).get("summary", ""),
            risk_notes=state.get("analyst_risk", {}).get("notes", ""),
        )

        # 呼叫 LLM summary，並把回傳當作 summary_text
        with GenCtx("investment_manager.llm", {"prompt_preview": safe_preview(prompt, 2000)}) as gen:
            raw = chat_text(prompt, temperature=0)
            gen.update(output={"raw_preview": safe_preview(raw, 1200)})

            def _parse_manager_sections(text: str) -> tuple[str, list[str]]:
                lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
                summary: list[str] = []
                risk: list[str] = []
                mode = None
                for ln in lines:
                    if ln.upper() == "SUMMARY:":
                        mode = "summary"
                        continue
                    if ln.upper() == "RISK:":
                        mode = "risk"
                        continue
                    if ln.startswith("-"):
                        item = ln.lstrip("-").strip()
                        if mode == "summary":
                            summary.append(item)
                        elif mode == "risk":
                            risk.append(item)
                return ("\n".join(summary).strip(), risk)

            final_summary_text = _clean_for_line(raw)
            if final_summary_text:
                final_state_dec = dict(preliminary)
                final_state_dec["summary"] = final_summary_text
                # 風險提醒就沿用風控分析師的 notes（穩定、可控）
                final_state_dec["risk"] = risk_notes[:3]
                state["final_decision"] = final_state_dec
                span.update(output={"final_decision": state["final_decision"]})
            else:
                span.update(output={"final_decision_fallback": state["final_decision"]})


    return state


def format_message_node(state: AgentState) -> AgentState:
    # 想在 Langfuse 看到哪些 input，就挑重要的放這裡
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
