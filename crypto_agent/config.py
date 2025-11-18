# config.py
import os
from dotenv import load_dotenv

load_dotenv()

# 幣種
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")

# Binance（抓 K 線其實不一定要 key，但先保留欄位）
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # 預設用 gpt-4o-mini

# 週線 MA 設定
WEEKLY_SMA_SHORT = 50
WEEKLY_SMA_LONG = 100

# 日線量價判斷用參數
VOLUME_SPIKE_FACTOR = 1.5    # 今天量 > 近 N 日均量 * 1.5 視為放量
VOLUME_DRY_FACTOR   = 0.7    # 今天量 < 近 N 日均量 * 0.7 視為縮量
VOLUME_LOOKBACK     = 20     # 計算平均量的天數
