# crypto_agent/main.py
import os
import certifi
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from linebot.v3.webhook import WebhookParser, MessageEvent
from linebot.v3.exceptions import InvalidSignatureError

from linebot.v3.messaging import (
    MessagingApi,
    ApiClient,
    Configuration,
    TextMessage,
    ReplyMessageRequest,
)

from graph_crypto_agent import run_with_graph

# 強制所有 urllib3/requests 類 client 用 certifi CA
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

print("[INFO] certifi =", certifi.where())
print("[INFO] SSL_CERT_FILE =", os.getenv("SSL_CERT_FILE"))

load_dotenv()

app = FastAPI()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
print(f"[INFO] LINE_CHANNEL_SECRET 長度 = {len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 0}")
print(f"[INFO] LINE_CHANNEL_TOKEN 長度 = {len(LINE_CHANNEL_TOKEN) if LINE_CHANNEL_TOKEN else 0}")

# --- LINE v3 init ---
parser = WebhookParser(LINE_CHANNEL_SECRET)

configuration = Configuration(access_token=LINE_CHANNEL_TOKEN)
# 強制 certifi CA
configuration.ssl_ca_cert = certifi.where()
api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        events = parser.parse(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        handle_event(event)

    return JSONResponse(content="OK")


def handle_event(event):
    # 只處理文字訊息
    if not isinstance(event, MessageEvent):
        return

    if not hasattr(event.message, "text"):
        return

    text = event.message.text.strip()
    print(f"[INFO] Received message: {text}")

    if "投資建議" in text:
        symbol_text = text.replace("投資建議", "").strip()
        symbol = f"{symbol_text.upper()}USDT"

        try:
            reply_text = run_with_graph(symbol)
        except Exception as e:
            reply_text = f"系統發生錯誤，請稍後再試\n{e}"

    else:
        reply_text = "請輸入「BTC投資建議」這類指令"

    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)],
        )
    )
