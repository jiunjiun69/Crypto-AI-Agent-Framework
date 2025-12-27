from __future__ import annotations
import os

# ---- Binance ----
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()

# ---- LLM ----
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ---- Langfuse ----
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

# 你 env 是 LANGFUSE_BASE_URL（本地 self-host 常用）
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000")
# alias，避免舊程式碼用 LANGFUSE_HOST 讀不到
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", LANGFUSE_BASE_URL)
