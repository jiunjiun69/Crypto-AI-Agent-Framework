from __future__ import annotations

import os
import re

from fastapi import FastAPI, HTTPException, Request

from dotenv import find_dotenv, load_dotenv

# load_dotenv()
# Load .env BEFORE importing modules that read env vars
load_dotenv(find_dotenv(usecwd=True))

# load_dotenv 再 import 任何會讀 config 的東西
from graph_crypto_agent import run_with_graph

import certifi

# 強制所有 urllib3/requests 類 client 用 certifi CA
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

print("[INFO] certifi =", certifi.where())
print("[INFO] SSL_CERT_FILE =", os.getenv("SSL_CERT_FILE"))

load_dotenv()

app = FastAPI()

TRIGGER_PREFIXES = ("!", "！", "@", "？", "?")
TRIGGER_COMMANDS = ("/crypto", "/c")  # 你也可以選擇支援指令型前綴

COMMON_TOKENS = {
    "BTC", "ETH", "SOL", "BNB", "ADA", "XRP", "DOGE", "AVAX", "LINK", "DOT",
    "MATIC", "OP", "ARB", "SUI", "APT", "ATOM", "LTC", "BCH", "TRX", "UNI",
}

def _strip_trigger(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return False, ""

    # 指令型（允許 "/crypto BTC投資建議"）
    low = t.lower()
    for cmd in TRIGGER_COMMANDS:
        if low.startswith(cmd):
            rest = t[len(cmd):].lstrip(" ：:")  # 去掉分隔符
            return True, rest

    # 符號型（允許 "!BTC投資建議"、"@我想抄底 BTC"）
    if t.startswith(TRIGGER_PREFIXES):
        rest = t[1:].lstrip(" ：:")
        return True, rest

    return False, t


def _has_common_token(text: str) -> bool:
    up = (text or "").upper()
    return any(re.search(rf"\b{tok}\b", up) for tok in COMMON_TOKENS)

def _extract_symbol(text: str) -> str | None:
    """
    從文字中抓幣種，回傳例如 'BTCUSDT'。
    抓不到就回傳 None（不要硬預設，避免使用者聊別的也噴BTC分析）。
    """
    print(f"[DEBUG] _extract_symbol input: {text}")
    t = (text or "").strip()

    # 1) 先處理中文別名（可以再擴充）
    zh_map = {
        "比特幣": "BTC",
        "大餅": "BTC",
        "以太幣": "ETH",
        "以太坊": "ETH",
        "以太": "ETH",
        "二餅": "ETH",
        "狗狗幣": "DOGE",
        "狗幣": "DOGE",
        "柴犬幣": "SHIB",
        "柴幣": "SHIB",
        "幣安幣": "BNB",
        "幣安": "BNB",
        "艾達幣": "ADA",
        "艾達": "ADA",
    }
    for k, v in zh_map.items():
        if k in t:
            return f"{v}USDT"

    # 2) 英文代號
    m = re.search(r"(?i)(?<![A-Za-z])([A-Za-z]{2,15})(?:USDT)?(?![A-Za-z])", t)
    if not m:
        return None

    token = m.group(1).upper()

    # 避免抓到非幣種單字
    blacklist = {"USDT", "AI", "AGENT", "BUY", "SELL", "HOLD"}
    if token in blacklist:
        return None

    # 如果使用者自己就打了 BTCUSDT 這種 pair，就直接用
    if token.endswith("USDT"):
        return token

    return f"{token}USDT"


def _looks_like_invest_question(text: str) -> bool:
    """
    不再當作「門檻」，只用來：抓不到幣時，要不要預設 BTC。
    """
    t = (text or "").strip()
    hints = ["投資", "建議", "買", "賣", "抄底", "加倉", "減倉", "止損", "停利", "做多", "做空", "回調", "回撤", "幣", "加密"]
    return any(h in t for h in hints)


def _is_crypto_question(text: str) -> bool:
    keywords = [
        "投資建議",
        "抄底",
        "重倉",
        "空手",
        "想賣",
        "賣出",
        "怕回撤",
        "回撤",
        "止損",
        "停損",
        "停利",
        "加倉",
        "減倉",
        "做多",
        "做空",
    ]
    return any(k in text for k in keywords)


@app.get("/health")
def health():
    return {"ok": True}


# ---- LINE webhook ----
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()

LINE_ENABLED = bool(LINE_CHANNEL_SECRET) and bool(LINE_CHANNEL_ACCESS_TOKEN)
print(f"[INFO] LINE Bot integration enabled: {LINE_ENABLED}")

if LINE_ENABLED:
    # line-bot-sdk v3
    from linebot.v3.webhook import WebhookParser
    from linebot.v3.messaging import (
        ApiClient,
        Configuration,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent

    configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
    parser = WebhookParser(LINE_CHANNEL_SECRET)

    @app.post("/line/callback")
    async def line_callback(request: Request):
        signature = request.headers.get("X-Line-Signature", "")
        body_bytes = await request.body()
        body = body_bytes.decode("utf-8")

        try:
            events = parser.parse(body, signature)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid signature")

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)

            for event in events:
                if not isinstance(event, MessageEvent):
                    continue
                if not isinstance(event.message, TextMessageContent):
                    continue

                text = (event.message.text or "").strip()
                if not text:
                    continue
                print(f"[INFO] Received LINE message: {text}")
                triggered, query = _strip_trigger(text)
                print(f"[INFO] Triggered: {triggered}, Query: {query}")
                # 沒有前綴：直接忽略，不回覆（避免干擾）
                if not triggered:
                    continue

                # 有前綴但沒內容：回使用說明
                if not query:
                    reply_text = (
                        "請用 ! 或 @ 開頭再問我，例如：\n"
                        "!BTC投資建議\n"
                        "!我想抄底 BTC\n"
                        "@我重倉 BTC 怕回撤\n"
                        "!BTC 想賣出 要不要先減倉\n"
                        "!ETH 做多可以嗎\n"
                    )
                else:
                    # 有前綴但不像幣圈問題：回使用說明（避免亂觸發 LLM）
                    # if (not _is_crypto_question(query)) and (not _has_common_token(query)):
                    #     reply_text = (
                    #         "我只處理幣圈投資問題，請用例如：\n"
                    #         "!BTC投資建議\n"
                    #         "!我想抄底 BTC\n"
                    #         "@我重倉 BTC 怕回撤\n"
                    #         "!BTC 想賣出 要不要先減倉\n"
                    #         "!ETH 做多可以嗎\n"
                    #     )
                    # else:
                    #     symbol = _extract_symbol(query)
                    #     reply_text = run_with_graph(symbol, user_text=query)
                    
                    symbol = _extract_symbol(query)
                    print(f"[INFO] 抓到的幣種: {symbol}")
                    # continue # for debug

                    if symbol is None:
                        # 抓不到幣種：如果看起來在問投資，就先用 BTCUSDT；否則給引導
                        if _looks_like_invest_question(query):
                            symbol = "BTCUSDT"
                            reply_text = run_with_graph(symbol, user_text=query)
                        else:
                            reply_text = (
                                "我目前主要提供加密貨幣投資判斷。\n"
                                "請在訊息中帶幣種，例如：\n"
                                "!BTC投資建議\n"
                                "!我想抄底 BTC\n"
                                "@我重倉 BTC 怕回撤\n"
                                "!BTC 想賣出 要不要先減倉\n"
                                "!ETH 做多可以嗎\n"
                            )
                    else:
                        reply_text = run_with_graph(symbol, user_text=query)

                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)],
                    )
                )

        return "OK"

else:

    @app.post("/line/callback")
    async def line_callback(_: Request):
        raise HTTPException(status_code=400, detail="LINE env not configured")
