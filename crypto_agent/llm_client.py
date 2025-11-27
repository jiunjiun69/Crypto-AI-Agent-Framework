from typing import Optional

from openai import OpenAI
from langchain_ollama import OllamaLLM

from config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    LLM_BACKEND,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


class LLMClient:
    """
    負責跟 LLM 對話，目前支援兩種 backend：
    - openai  （官方 API）
    - ollama  （本地 / Colab OLLAMA_HOST）

    注意：
    - 這個 class 現在 **只負責呼叫 LLM**，不再直接呼叫 Langfuse。
    - Langfuse 的觀測／tracing 統一在 graph_crypto_agent.py + observability.py 處理。
    """

    def __init__(self) -> None:
        self.backend = (LLM_BACKEND or "openai").lower()

        # --- 初始化 LLM backend ---
        if self.backend == "ollama":
            # 使用 LangChain 的 OllamaLLM
            self.llm = OllamaLLM(
                model=OLLAMA_MODEL,
                base_url=OLLAMA_BASE_URL,
            )
            self.client: Optional[OpenAI] = None
            print(f"[INFO] LLM backend = OLLAMA ({OLLAMA_MODEL}) @ {OLLAMA_BASE_URL}")
        else:
            # 使用 OpenAI 官方 client
            if not OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY 未設定，無法使用 OpenAI backend")
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            self.llm = None
            print(f"[INFO] LLM backend = OpenAI ({OPENAI_MODEL})")

    # ----------------------------------------------------
    # 封裝一個簡單的 summarize(prompt) 給上層使用
    # ----------------------------------------------------
    def summarize(self, prompt: str) -> str:
        """
        統一入口：
        - backend = openai -> 呼叫 official OpenAI Chat Completions
        - backend = ollama -> 呼叫 LangChain OllamaLLM.invoke()
        """
        if self.backend == "ollama":
            if self.llm is None:
                raise RuntimeError("Ollama LLM 尚未初始化")
            # LangChain LLM 介面：直接用 invoke()
            response_text = self.llm.invoke(prompt)
        else:
            if self.client is None:
                raise RuntimeError("OpenAI client 尚未初始化")
            resp = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=0.3,
            )
            response_text = resp.choices[0].message.content

        return response_text
