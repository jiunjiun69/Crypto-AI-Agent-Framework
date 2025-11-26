from typing import Optional

from openai import OpenAI
from langchain_ollama import OllamaLLM

from config import (
    LLM_BACKEND,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


class LLMClient:
    """
    Advice Agent 後端：
    - backend = "openai": 走 OpenAI Chat Completions
    - backend = "ollama": 走本地 / 遠端 Ollama（透過 langchain-ollama）
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.backend = (backend or LLM_BACKEND).lower()

        if self.backend == "ollama":
            # Ollama backend（可以是本機 localhost，也可以是你 Colab + ngrok 那個 URL）
            base_url = OLLAMA_BASE_URL
            mdl = model or OLLAMA_MODEL

            self.llm = OllamaLLM(
                model=mdl,
                base_url=base_url,  # 例如 https://xxxx.ngrok-free.app/
            )
        else:
            # 預設使用 OpenAI
            self.backend = "openai"
            self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)
            self.model = model or OPENAI_MODEL or "gpt-4o-mini"

    def summarize(self, prompt: str) -> str:
        """
        給一個完整的 prompt（已經包含 persona、週線/日線說明），
        回傳繁體中文建議。
        """
        if self.backend == "ollama":
            # LangChain Ollama：直接把整個 prompt 丟進去
            res = self.llm.invoke(prompt)
            return (res or "").strip()

        # OpenAI Chat Completions 版本
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
        return (resp.choices[0].message.content or "").strip()
