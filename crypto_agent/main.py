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

def _extract_symbol(text: str) -> str:
    """
    Extract token like BTC/ETH/SOL... and convert to {TOKEN}USDT.
    If none found, default BTCUSDT.
    """
    m = re.search(r"\b([A-Za-z]{2,10})\b", text)
    if not m:
        return "BTCUSDT"

    token = m.group(1).upper()
    if token in {"USDT", "AI", "AGENT"}:
        return "BTCUSDT"
    return f"{token}USDT"


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

                if not _is_crypto_question(text):
                    reply_text = (
                        "你可以直接問：\n"
                        "- BTC投資建議\n"
                        "- 我想抄底 BTC\n"
                        "- 我重倉 BTC 怕回撤\n"
                        "- 我空手 想等回調\n"
                        "- BTC 想賣出 要不要先減倉\n"
                        "- ETH 做多可以嗎\n"
                    )
                else:
                    symbol = _extract_symbol(text)
                    
                    reply_text = run_with_graph(symbol, user_text=text)
                    # try:
                    #     reply_text = run_with_graph(symbol, user_text=text)
                    # except Exception as e:
                    #     reply_text = f"系統發生錯誤，請稍後再試\n{e}"

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
