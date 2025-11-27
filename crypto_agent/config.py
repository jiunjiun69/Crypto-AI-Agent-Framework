import os
from dotenv import load_dotenv

load_dotenv()

# 幣種
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")

# Binance
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ---- LLM backend 選擇 ----
# openai / ollama
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").lower()

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # 預設用 gpt-4o-mini

# Ollama （可接本機 or Colab）
# 優先使用 OLLAMA_BASE_URL，沒設才 fallback OLLAMA_HOST
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")  # 預設用 llama3.2:3b

# 週線 MA 設定
WEEKLY_SMA_SHORT = 50
WEEKLY_SMA_LONG = 100

# 日線量價判斷用參數
VOLUME_SPIKE_FACTOR = 1.5    # 今天量 > 近 N 日均量 * 1.5 視為放量
VOLUME_DRY_FACTOR   = 0.7    # 今天量 < 近 N 日均量 * 0.7 視為縮量
VOLUME_LOOKBACK     = 20     # 計算平均量的天數

# Langfuse (觀測 / tracing)
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "")
