# llm_client.py
from typing import Optional

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        # 用環境變數為主，允許呼叫時 override
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)
        self.model = model or OPENAI_MODEL or "gpt-4o-mini"

    def summarize(self, prompt: str) -> str:
        """
        給一個長 prompt（含你的週線/日線分析文字），
        回傳一段繁體中文的建議說明。
        """

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位偏保守、以風險控管為主的現貨加密貨幣顧問，"
                        "用繁體中文回答，條列清楚、不要給精準價格與槓桿建議。"
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        # 取第一個回覆
        return (resp.choices[0].message.content or "").strip()