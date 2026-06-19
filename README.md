# Trump Truth Social Monitor v4

這個專案會監控 Donald Trump 的 Truth Social 最新貼文，抓到尚未處理的新貼文後，透過 Hermes 翻譯成繁體中文，再送到指定的 Telegram 對話。

目前主程式是 [trump_monitor_v4.py](./trump_monitor_v4.py)。

## 功能

- 使用 Playwright 抓取 `https://truthsocial.com/@realDonaldTrump`
- 過濾 `Sponsored` 內容並抽出貼文 ID、時間、正文
- 僅從正文容器（`[data-testid="markup"]` 等）擷取文字，純媒體／轉發等無正文貼文會被略過、不會誤送
- 時間優先抓 `<time>` 的 `datetime` / `title` 屬性，輸出絕對時間（例如 `Jun 19, 2026, 8:33 PM`）而非 `2h` 之類的相對時間
- 用本地記錄檔去重；所有看過的貼文 ID（含跳過的）都會記錄，避免下次重複處理
- 呼叫 `hermes chat -Q -q --provider openrouter --model google/gemma-4-31b-it:free ...` 進行繁中翻譯
- 翻譯完成後直接呼叫 Telegram Bot API 發送（不再透過 Hermes 工具），訊息切段優先在換行/空白處避免截斷句子或多位元組字元
- 內建 timeout / retry：Hermes 翻譯與 Telegram 發送都有獨立重試
- subprocess 與 HTTP 透過 `asyncio.to_thread` 執行，避免阻塞 Playwright 事件迴圈
- 內建單實例鎖，避免 cron 與手動執行重疊導致重複發送

## 目前實作細節

- 抓取方式：解析頁面 DOM，不是直接打 Truth Social API
- 正文容器選擇器：`[data-testid="markup"], [data-markup="true"], .status__content, [data-testid="status__content"]`
- 已讀 ID 檔案：`/home/jimmy/.openclaw/workspace/memory/trump_last_truth_v4.txt`（保留最近 100 筆）
- Hermes 路徑：`/home/jimmy/.local/bin/hermes`
- Telegram 目標：程式內固定使用 chat id `1032617150`
- Telegram Bot Token：優先讀環境變數 `TELEGRAM_BOT_TOKEN`，否則從 `/home/jimmy/.hermes/.env` 解析
- 單實例鎖檔：`/tmp/trump_truth_monitor_v4.lock`

## 安裝需求

- Python 3.8+
- [Playwright](https://playwright.dev/python/docs/intro)
- 已可正常執行的 [Hermes Agent](https://github.com/NousResearch/hermes-agent)

安裝 Playwright：

```bash
pip install playwright
playwright install chromium
```

## 執行方式

手動執行：

```bash
python3 trump_monitor_v4.py
```

若程式偵測到已有另一個執行中的實例，會直接跳過，避免重複發送。

## 目前 cron 排程

這台機器目前有設定每 30 分鐘執行一次：

```cron
*/30 * * * * /usr/bin/python3 /home/jimmy/.openclaw/workspace/trump-truth-monitor-v4/trump_monitor_v4.py >>/home/jimmy/.openclaw/workspace/cron-results/trump-truth-monitor-v4/run.log 2>&1
```

## 除錯與排查

最重要的執行紀錄在：

```text
/home/jimmy/.openclaw/workspace/cron-results/trump-truth-monitor-v4/run.log
```

常見判讀方式：

- 出現 `沒有新貼文需要翻譯。`：此次抓取正常，所有貼文都已記錄過或無正文
- 出現 `article[N] skip: empty content (post_id=...)`：該篇沒有正文（媒體/轉發），會被記錄為已處理、不再重試
- 出現 `hermes 翻譯貼文...` 後失敗：通常是 Hermes / 模型端超時或失敗，會自動重試 3 次
- 出現 `telegram 發送 chunk X/Y`：表示已進入發送階段；失敗時會重試 3 次
- 出現 `已有另一個 trump_monitor_v4.py 執行中`：代表有重疊執行，這次已被鎖擋下

## 已知限制

- Truth Social 頁面結構或 Cloudflare 行為變動時，抓取可能失效（DOM selector 已於 2026-06 從 `.status__content` 改為 `[data-testid="markup"]`）
- Telegram 多段訊息中若部分 chunk 重試後仍失敗，下次會重送整篇貼文，已送出的 chunk 將出現重複
- 翻譯失敗時不會 fallback 送原文，只會跳過該篇貼文等下次重試

## 授權

MIT License
