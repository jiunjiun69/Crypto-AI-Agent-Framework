# Crypto-AI-Agent-Framework

以 **AI Agent Framework** 為核心概念，實作一套可直接使用的 **加密貨幣現貨投資 AI Agent**，目前聚焦於 **BTC 現貨分析與投資建議**。  
目標是讓使用者透過 LINE Bot 或本地指令快速獲得：

> 📌 「現在 BTC 形勢如何？我該怎麼做？」  
>
> → AI 依據市場資料與你的意圖，提供清楚的結論、摘要與風險提示

---

## 🧾 為什麼需要 Crypto AI Agent？

在幣圈投資，要同時追蹤：

- 長期趨勢與週線趨勢（例如 SMA）
- 日線量價型態與技術結構
- 使用者具體意圖（抄底 / 想賣出 / 怕回撤 / 重倉）
- 風險控管與合理建議

對於 **有本業、時間有限的散戶投資人**，很難每天追行情、判讀資料、整合結論。  
這個專案的目標是搭建一套：

> **可 Query + 可解釋 + 可 trace 的 AI 投資助理**

既能做資料蒐集、技術分析，又能跟使用者對話並提供建議。

---

## 🧠 系統架構（目前版）

整個系統核心由：

📌 **LangGraph Pipeline**  
📌 **LangFuse	Observability**  
📌 **LLM 分析與 Decision 層**  
📌 **LINE Bot / local CLI 介面**

如下圖：

```mermaid
flowchart LR
    U["使用者 LINE 聊天或 CLI"] -->|輸入指令| I[Interface]
    I --> C[Crypto Agent Runner]
    
    subgraph Pipeline["LangGraph Pipeline"]
        F[fetch_and_analyze]
        A[multi_analyst 
        週線/daily/risk]
        M[manager_merge
        加權票選]
        R[format_message]
    end
    
    C --> F --> A --> M --> R --> O["Final Message"]

    subgraph LLMBackend["LLM Backend"]
        LLM[(Ollama / OpenAI / vLLM / OpenRouter)]
    end
    A --> LLM
    A --> FUSE["Langfuse Trace"]
````

## Demo

<img src="https://github.com/jiunjiun69/Crypto-AI-Agent-Framework/blob/main/img_v2/v2_Demo.gif" alt="v2_Demo" width="800"/>

---

## 📌 系統特色

### ✔ 使用者意圖驅動分析（Intent Driven）

系統會從輸入中解析使用者意圖：

| 使用者輸入      | Intent         |
| ---------- | -------------- |
| `BTC 投資建議` | general_advice |
| `我想抄底 BTC` | bottom_fishing |
| `我怕回撤`     | risk_averse    |
| `想賣出 BTC`  | take_profit    |
| `我重倉 BTC`  | heavy_position |

每種意圖會影響分析師投票權重與解讀重點。

---

### ✔ 多分析師共同評估

三位 LLM 分析師各司其職：

* **analyst_weekly** — 週線趨勢分析
* **analyst_daily** — 日線量價型態分析
* **analyst_risk**  — 風險與倉位控制分析

每位分析師會輸出嚴格 JSON 格式的分析結果：

```jsonc
{
  "ok": true,
  "focus": "weekly",
  "decision": "...(buy/hold/sell)...",
  "summary": "...",
  "confidence": "...(high/medium/low)...",
  "key_levels": {"support":"...", "resistance":"..."},
  "notes": "...",
  "missing": []
}
```

---

### ✔ Intent 加權投票決策

根據使用者意圖，調整每位分析師的重要性：

| Intent         | weekly | daily | risk |
| -------------- | ------ | ----- | ---- |
| general_advice | 1.0    | 1.0   | 1.0  |
| bottom_fishing | 0.5    | 1.5   | 1.0  |
| risk_averse    | 0.5    | 1.0   | 1.5  |
| take_profit    | 1.0    | 0.8   | 1.4  |
| heavy_position | 1.0    | 1.2   | 0.8  |

最終結論由 **加權投票得分最高者** 決定。

---

### ✔ 可觀測的 Trace（Langfuse）

系統與各 LLM 呼叫流程都透過 Langfuse 建立 Trace：

```
crypto_agent.run
├ fetch_and_analyze
├ analyst_weekly
│  └ analyst_weekly.llm
├ analyst_daily
│  └ analyst_daily.llm
├ analyst_risk
│  └ analyst_risk.llm
├ manager_merge
└ format_message
```

在 Langfuse UI 可以逐層檢視：

* prompt preview
* llm raw preview
* final outputs
* metadata / debug logs

---

## 📦 專案目錄

```
crypto_agent/
  config.py
  data_binance.py
  indicators.py
  llm_client.py
  line_formatter.py
  graph_crypto_agent.py
  main.py
  run_local.py
  requirements.txt
  .env
```

---

## 🛠 安裝與使用

### 1) 安裝依賴

```bash
pip install -r requirements.txt
```

---

### 2) 建立 .env 設定檔

內容如下：

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

BINANCE_API_KEY=
BINANCE_API_SECRET=
SYMBOL=BTCUSDT

# LLM backend
LLM_BACKEND=ollama
OLLAMA_MODEL=llama3.2:3b
OLLAMA_BASE_URL=http://localhost:11434

# Langfuse
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=http://localhost:3000

# LINE Bot
LINE_CHANNEL_SECRET=
LINE_CHANNEL_TOKEN=
```

⚠ **請勿將 .env 提交到 GitHub**

---

### 3) 本地執行

```bash
python run_local.py
```

---

### 4) LINE Webhook 測試

```bash
ngrok http 8000
```

將 ngrok 產出的 URL 貼到 LINE Developer Console 的 webhook URL

---

## 📊 使用示例與輸出

### 👉 一般投資建議

輸入：

```
BTC 投資建議
```

回傳：

```
【BTCUSDT 形勢分析（AI Agent）】

✅ 結論：HOLD

🧠 重點摘要：
近期日線顯示強烈的上升趨勢，短期內可能再次創高…

⚠️ 風險提醒：
- 近期波動仍大
- 需密切觀察市場趨勢
```

---

### 👉 抄底意圖

輸入：

```
我想抄底 BTC
```

回傳：

```
【BTCUSDT 形勢分析（AI Agent）】

✅ 結論：BUY

🧠 重點摘要：
短線支撐區出現反轉信號，RSI 底背離強化了抄底機會…

⚠️ 風險提醒：
- 若跌破支撐請重新評估策略
```

---

## 🔍 Langfuse 觀測範例

在 Langfuse UI 你可以看到：

| Span 名稱           | 說明                   |
| ----------------- | -------------------- |
| fetch_and_analyze | 資料抓取與技術指標            |
| analyst_weekly    | 週線分析 prompt + result |
| analyst_daily     | 日線分析 prompt + result |
| analyst_risk      | 風控分析 prompt + result |
| manager_merge     | 投資經理加權決策             |
| format_message    | 產出最終文字回覆             |

---

## 📊 指標與策略說明

### 1) 週線 Regime

週線使用 SMA50 / SMA100 做 trend 判斷
並依照距離判別 bull / bear / warning / neutral

### 2) 日線量價

日線量價結合成交量與 K 線變化給出 pattern

---

## 🛣 假設想繼續玩的未來規劃（Roadmap）

* 支援更多幣種（ETH、SOL…）
* 支援更多 LLM backend（OpenRouter / vLLM）
* 自動定時推播（Cron + LINE）
* 支援策略 backtest & feedback loop

---

## ⚠️ 免責聲明

本專案僅作技術研究與學習用途，
**不構成任何投資建議。**
加密貨幣波動大，請自行評估風險。