import os

try:
    from langfuse import Langfuse  # pip install langfuse
except ImportError:
    Langfuse = None


def get_langfuse():
    """
    回傳一個已設定好的 Langfuse client，如果沒啟用就回傳 None。
    條件：
      - 安裝了 langfuse 套件
      - LANGFUSE_ENABLED=true
      - LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY 存在
    """
    if Langfuse is None:
        print("[INFO] Langfuse 套件未安裝，略過觀測。")
        return None

    enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
    if not enabled:
        print("[INFO] LANGFUSE_ENABLED != true，略過觀測。")
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = (
        os.getenv("LANGFUSE_HOST")
        or os.getenv("LANGFUSE_BASE_URL")
        or "http://localhost:3000"
    )

    if not public_key or not secret_key:
        print("[WARN] 缺少 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY，略過觀測。")
        return None

    lf = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )

    # 做一次 auth 檢查，錯了就直接關掉
    try:
        lf.auth_check()
        print(f"[INFO] Langfuse client 已初始化，host = {host}")
    except Exception as e:
        print(f"[WARN] Langfuse 認證失敗：{e}，關閉觀測。")
        return None

    return lf


# 給整個專案共用的 client
langfuse = get_langfuse()
