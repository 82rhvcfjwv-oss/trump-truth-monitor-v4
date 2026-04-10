# Trump Truth Social Monitor v4

這個專案會監控 Donald Trump 的 Truth Social 最新貼文，抓到尚未處理的新貼文後，透過 OpenClaw 翻譯成繁體中文，再送到指定的 Telegram 對話。

目前主程式是 [trump_monitor_v4.py](./trump_monitor_v4.py)。

## 功能

- 使用 Playwright 抓取 `https://truthsocial.com/@realDonaldTrump`
- 過濾 `Sponsored` 內容並抽出貼文 ID、時間、正文
- 用本地記錄檔去重，避免重複處理同一篇貼文
- 呼叫 `openclaw agent` 進行繁中翻譯
- 呼叫 `openclaw message send --channel telegram --target ...` 發送到 Telegram
- 內建 timeout / retry，降低 OpenClaw 偶發卡住造成的失敗率
- 內建單實例鎖，避免 cron 與手動執行重疊導致重複發送

## 目前實作細節

- 抓取方式：解析頁面 DOM，不是直接打 Truth Social API
- 已讀 ID 檔案：`/home/jimmy/.openclaw/workspace/memory/trump_last_truth_v4.txt`
- OpenClaw 路徑：`/home/jimmy/.npm-global/bin/openclaw`
- Telegram 目標：程式內固定使用 `--target 1032617150`
- 單實例鎖檔：`/tmp/trump_truth_monitor_v4.lock`

## 安裝需求

- Python 3.8+
- [Playwright](https://playwright.dev/python/docs/intro)
- 已可正常執行的 [OpenClaw](https://github.com/82rhvcfjwv-oss/openclaw)

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

- 出現 `沒有新貼文。`：此次抓取正常，但沒有新文
- 出現 `openclaw 翻譯貼文...` 後失敗：通常是 OpenClaw / 模型端超時或失敗
- 出現 `送出到 Telegram...`：表示已進入發送階段
- 出現 `已有另一個 trump_monitor_v4.py 執行中`：代表有重疊執行，這次已被鎖擋下

## 已知限制

- Truth Social 頁面結構或 Cloudflare 行為變動時，抓取可能失效
- `openclaw message send` 有時會回應很慢，所以目前設定了較長的 send timeout
- 目前翻譯失敗時不會 fallback 送原文，只會跳過該篇貼文

## 授權

MIT License
