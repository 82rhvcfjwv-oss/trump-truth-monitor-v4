import asyncio
import fcntl
import os
import re
import random
import subprocess
import time
from datetime import datetime
from playwright.async_api import async_playwright

# 配置
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
LAST_ID_FILE = '/home/jimmy/.openclaw/workspace/memory/trump_last_truth_v4.txt'
HERMES_PATH = '/home/jimmy/.local/bin/hermes'
HERMES_PROVIDER = 'openrouter'
HERMES_MODEL = 'google/gemma-4-31b-it:free'
TELEGRAM_CHAT_ID = "1032617150"
LOCK_FILE = '/tmp/trump_truth_monitor_v4.lock'
HERMES_TRANSLATE_TIMEOUT = 120
HERMES_SEND_TIMEOUT = 300
HERMES_TRANSLATE_RETRIES = 3
HERMES_SEND_RETRIES = 3
HERMES_RETRY_DELAY_SECONDS = 5

def clean_content(text):
    """清理並去重貼文內容"""
    if not text:
        return ""
    
    text = text.strip()
    
    # 檢查字串是否由兩個完全相同的部分組成 (常見的重複抓取現象)
    if len(text) > 20:
        mid = len(text) // 2
        # 考慮到可能存在的微小空白差異
        part1 = text[:mid].strip()
        part2 = text[mid:].strip()
        if part1 == part2:
            return part1
            
    return text

async def fetch_trump_posts():
    # 1. 連線前隨機等待 5 至 30 秒
    wait_time = random.uniform(5, 30)
    print(f"[{datetime.now()}] 隨機等待 {wait_time:.2f} 秒後開始抓取...")
    await asyncio.sleep(wait_time)

    posts = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1280, 'height': 2000}
        )
        
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        url = 'https://truthsocial.com/@realDonaldTrump'
        print(f"[{datetime.now()}] 正在抓取: {url}")
        
        try:
            await page.goto(url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(8) # 等待渲染
            
            # 滾動以確保載入更多
            await page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(4)
            
            # 獲取所有貼文元素
            articles = await page.query_selector_all('article, div[data-testid="status"]')
            print(f"找到 {len(articles)} 個潛在貼文元素")
            
            for article in articles:
                inner_text = await article.inner_text()
                if "Sponsored" in inner_text:
                    continue
                
                id_link = await article.query_selector('a[href*="/posts/"]')
                if not id_link:
                    continue
                    
                href = await id_link.get_attribute('href')
                if "@realDonaldTrump" not in href:
                    continue
                    
                match = re.search(r'/posts/(\d+)', href)
                post_id = match.group(1) if match else None
                if not post_id:
                    continue
                
                # 獲取內容 - 改進去重邏輯
                content = ""
                content_elem = await article.query_selector('.status__content, [data-testid="status__content"]')
                if content_elem:
                    # 抓取所有段落並去重
                    p_elems = await content_elem.query_selector_all('p')
                    if p_elems:
                        unique_p = []
                        seen_p = set()
                        for p in p_elems:
                            p_text = (await p.inner_text()).strip()
                            if p_text and p_text not in seen_p:
                                unique_p.append(p_text)
                                seen_p.add(p_text)
                        content = "\n\n".join(unique_p)
                    else:
                        content = await content_elem.inner_text()
                else:
                    paragraphs = await article.query_selector_all('p')
                    unique_p = []
                    seen_p = set()
                    for p in paragraphs:
                        p_text = (await p.inner_text()).strip()
                        if p_text and p_text not in seen_p:
                            unique_p.append(p_text)
                            seen_p.add(p_text)
                    content = "\n\n".join(unique_p)
                
                # 最後一次字串層級的清理
                content = clean_content(content)
                
                # 獲取貼文時間
                time_elem = await article.query_selector('time')
                timestamp = "未知時間"
                if time_elem:
                    timestamp = await time_elem.get_attribute('datetime') or await time_elem.inner_text()
                
                if content.strip():
                    posts.append({
                        'id': post_id,
                        'content': content.strip(),
                        'timestamp': timestamp,
                        'url': f"https://truthsocial.com{href}"
                    })
            
            unique_posts = {p['id']: p for p in posts}.values()
            return sorted(list(unique_posts), key=lambda x: x['id'], reverse=True)
            
        except Exception as e:
            print(f"錯誤: {e}")
            return []
        finally:
            await browser.close()

def get_last_ids():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_ids(ids):
    os.makedirs(os.path.dirname(LAST_ID_FILE), exist_ok=True)
    with open(LAST_ID_FILE, 'w') as f:
        for pid in sorted(list(ids), reverse=True)[:100]:
            f.write(f"{pid}\n")


def acquire_single_instance_lock():
    lock_fp = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fp.write(str(os.getpid()))
        lock_fp.flush()
        return lock_fp
    except BlockingIOError:
        lock_fp.close()
        return None

def build_translation_prompt(content, timestamp):
    return (
        "請將以下貼文翻譯成繁體中文，只翻譯正文，保留時間資訊。"
        f"輸出格式固定如下：\n貼文時間：{timestamp}\n貼文內容：<翻譯後內容>\n\n"
        f"原文：{content}"
    )


def run_hermes_command(cmd, action_label, timeout_seconds, retries):
    for attempt in range(1, retries + 1):
        print(
            f"{action_label}（第 {attempt}/{retries} 次，timeout={timeout_seconds}s）..."
        )
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if stderr:
                print(stderr)
            return stdout
        except subprocess.TimeoutExpired:
            print(f"❌ {action_label}逾時（>{timeout_seconds}s）")
        except subprocess.CalledProcessError as e:
            error_output = (e.stderr or e.stdout or "").strip()
            print(f"❌ {action_label}失敗: {error_output}")
        except Exception as e:
            print(f"❌ {action_label}發生未預期錯誤: {e}")

        if attempt < retries:
            print(f"{HERMES_RETRY_DELAY_SECONDS} 秒後重試...")
            time.sleep(HERMES_RETRY_DELAY_SECONDS)

    return None


def normalize_hermes_output(output):
    if not output:
        return ""
    lines = output.strip().splitlines()
    cleaned = []
    for line in lines:
        if line.strip().startswith("session_id:"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def translate_with_hermes(content, timestamp):
    prompt_message = build_translation_prompt(content, timestamp)
    cmd = [
        HERMES_PATH,
        "chat",
        "-Q",
        "-q",
        "--provider",
        HERMES_PROVIDER,
        "--model",
        HERMES_MODEL,
        prompt_message,
    ]

    translated = run_hermes_command(
        cmd,
        f"hermes 翻譯貼文（時間：{timestamp}）",
        HERMES_TRANSLATE_TIMEOUT,
        HERMES_TRANSLATE_RETRIES,
    )
    return normalize_hermes_output(translated)


def send_to_telegram(message):
    send_prompt = (
        "請使用 send_message 工具把以下訊息發送到 Telegram。"
        f"target 請使用 {TELEGRAM_CHAT_ID}。"
        "發送成功只回覆 SENT，失敗回覆 ERROR。\n\n"
        f"訊息內容：\n{message}"
    )
    cmd = [
        HERMES_PATH,
        "chat",
        "-Q",
        "-q",
        "--provider",
        HERMES_PROVIDER,
        "--model",
        HERMES_MODEL,
        send_prompt,
    ]
    result = run_hermes_command(
        cmd,
        "透過 hermes 送出到 Telegram",
        HERMES_SEND_TIMEOUT,
        HERMES_SEND_RETRIES,
    )
    normalized = normalize_hermes_output(result)
    # 寬鬆匹配：只要包含 SENT 或 成功-send 類關鍵字即可
    return bool(normalized) and any(keyword in normalized.upper() for keyword in ["SENT", "成功", "SUCCESS"])


def process_with_hermes(content, timestamp):
    translated = translate_with_hermes(content, timestamp)
    if not translated:
        return False
    return send_to_telegram(translated)

async def main():
    posts = await fetch_trump_posts()
    if not posts:
        print("未抓取到任何貼文。")
        return
    
    last_ids = get_last_ids()
    new_posts = [p for p in posts if p['id'] not in last_ids]
    
    if not new_posts:
        print("沒有新貼文。")
        return
    
    print(f"發現 {len(new_posts)} 條新貼文！")
    
    for post in reversed(new_posts): # 從舊到新處理
        success = process_with_hermes(post['content'], post['timestamp'])
        if success:
            last_ids.add(post['id'])
        else:
            print(f"貼文 {post['id']} 處理失敗，跳過更新 ID")
    
    save_ids(last_ids)
    print("更新完成。")

if __name__ == "__main__":
    lock_fp = acquire_single_instance_lock()
    if lock_fp is None:
        print("已有另一個 trump_monitor_v4.py 執行中，這次跳過。")
    else:
        try:
            asyncio.run(main())
        finally:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
            lock_fp.close()
