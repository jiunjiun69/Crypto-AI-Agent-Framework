# llm_client.py
from typing import Optional
from openai import OpenAI
from config import OPENAI_API_KEY


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4.1-mini"):
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)
        self.model = model

    def summarize(self, prompt: str) -> str:
        resp = self.client.responses.create(
            model=self.model,
            input=prompt,
        )
        # 簡單取第一段文字
        return resp.output[0].content[0].text
