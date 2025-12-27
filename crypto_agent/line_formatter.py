from __future__ import annotations
from typing import Any, Dict, List, Optional
import json


def build_prompt_for_llm(
    symbol: str,
    weekly_regime: str,
    weekly_row: Dict[str, float],
    daily_pattern: Dict[str, Any],
    daily_candles: Optional[List[Dict[str, Any]]] = None,
) -> str:
    candles_txt = ""
    if daily_candles:
        rows = []
        for c in daily_candles[-14:]:
            rows.append(
                f"{c['date']} O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']} V:{c['volume']}"
            )
        candles_txt = "\n".join(rows)

    return f"""
【交易對】{symbol}

【週線趨勢】{weekly_regime}
- close={weekly_row.get('close')}
- sma50={weekly_row.get('sma50')}
- sma100={weekly_row.get('sma100')}

【日線量價型態】
{json.dumps(daily_pattern, ensure_ascii=False)}

【最近 14 根日線（daily_candles）】
{candles_txt}
""".strip()


def format_line_message(symbol: str, result: Any) -> str:
    header = f"【{symbol} 形勢分析（AI Agent）】\n"

    if isinstance(result, dict):
        decision = result.get("final_decision", "").upper()
        summary = result.get("summary", "")
        plan = result.get("plan", "")
        risk = result.get("risk", [])

        lines = [header]
        if decision:
            lines.append(f"✅ 結論：{decision}\n")

        if summary:
            lines.append("🧠 重點摘要：")
            lines.append(summary.strip())
            lines.append("")

        if plan:
            lines.append("📌 操作建議：")
            lines.append(plan.strip())
            lines.append("")

        if isinstance(risk, list) and risk:
            lines.append("⚠️ 風險提醒：")
            for r in risk[:3]:
                lines.append(f"- {str(r).strip()}")

        return "\n".join(lines).strip()

    # fallback：result 是純文字
    return (header + "\n" + str(result)).strip()