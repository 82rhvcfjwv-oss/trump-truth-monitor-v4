# Trump Truth Social Monitor v4 🇺🇸

這是一個自動化監控 Donald Trump 在 Truth Social 上最新貼文的工具。它使用 Playwright 模擬瀏覽器行為以繞過 Cloudflare 保護，並整合 OpenClaw 進行自動翻譯與 Telegram 發送。

## 🌟 功能特點

- **規避偵測**：使用 Playwright 模擬真實瀏覽器行為，有效繞過 Cloudflare 驗證。
- **隨機延遲**：連線前隨機等待 5-30 秒，降低被識別為爬蟲的風險。
- **精確抓取**：自動擷取貼文內容與發佈時間，並過濾廣告 (Sponsored)。
- **智能去重**：包含段落級別與內容層級的去重邏輯，防止重複內容。
- **OpenClaw 整合**：自動呼叫 OpenClaw 將內容翻譯為繁體中文，並直接發送到指定的 Telegram 頻道。

## 🛠 安裝要求

- Python 3.8+
- [Playwright](https://playwright.dev/python/docs/intro)
- [OpenClaw](https://github.com/82rhvcfjwv-oss/openclaw) (需安裝於全域路徑)

## 🚀 快速開始

1. **安裝依賴**：
   ```bash
   pip install playwright requests
   playwright install chromium
   ```

2. **設定環境變數**（選用，若 OpenClaw 內部已設定則可省略）：
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

3. **執行監控**：
   ```bash
   python3 trump_monitor_v4.py
   ```

## ⚙️ 設定說明

核心設定位於 `trump_monitor_v4.py` 的頂部：
- `LAST_ID_FILE`: 儲存已讀貼文 ID 的路徑。
- `OPENCLAW_PATH`: OpenClaw 執行檔的絕對路徑。
- `TELEGRAM_CHAT_ID`: 目標 Telegram 頻道的 ID。

## 📝 授權

MIT License
