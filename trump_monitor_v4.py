import asyncio
import fcntl
import json
import os
import random
import re
import subprocess
import time
import urllib.request
from datetime import datetime

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# 基本配置
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)
LAST_ID_FILE = '/home/jimmy/.openclaw/workspace/memory/trump_last_truth_v4.txt'
LAST_ID_KEEP = 100
LOCK_FILE = '/tmp/trump_truth_monitor_v4.lock'

# Hermes 翻譯
HERMES_PATH = '/home/jimmy/.local/bin/hermes'
HERMES_PROVIDER = 'openrouter'
HERMES_MODEL = 'google/gemma-4-31b-it:free'
HERMES_TRANSLATE_TIMEOUT = 120
HERMES_TRANSLATE_RETRIES = 3
HERMES_RETRY_DELAY_SECONDS = 5

# 抓取行為
FETCH_WAIT_MIN_SECONDS = 5
FETCH_WAIT_MAX_SECONDS = 30
PAGE_GOTO_TIMEOUT_MS = 60000
PAGE_RENDER_WAIT_SECONDS = 8
SCROLL_PIXELS = 4500
SCROLL_WAIT_SECONDS = 4
POST_BODY_SELECTOR = (
    '[data-testid="markup"], [data-markup="true"], '
    '.status__content, [data-testid="status__content"]'
)
TRUTH_URL = 'https://truthsocial.com/@realDonaldTrump'

# Telegram
TELEGRAM_CHAT_ID = "1032617150"
TELEGRAM_CHUNK_LIMIT = 3900
TELEGRAM_TIMEOUT_SECONDS = 30
TELEGRAM_RETRIES = 3
TELEGRAM_RETRY_DELAY_SECONDS = 3


async def dedupe_paragraphs(element):
    """從元素中抓取所有 <p>，去重後以雙換行串接；若沒有 <p> 回傳 None。"""
    p_elems = await element.query_selector_all('p')
    if not p_elems:
        return None
    seen = set()
    unique = []
    for p in p_elems:
        text = (await p.inner_text()).strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(text)
    return "\n\n".join(unique)


async def extract_post_content(article):
    """只從正文容器抓內容；找不到或為空就回傳空字串。"""
    content_elem = await article.query_selector(POST_BODY_SELECTOR)
    if not content_elem:
        return ""
    deduped = await dedupe_paragraphs(content_elem)
    if deduped:
        return deduped.strip()
    return (await content_elem.inner_text()).strip()


async def extract_post_timestamp(article):
    """偏好絕對時間（datetime / title 屬性），最後才回退到顯示文字。"""
    time_elem = await article.query_selector('time')
    if not time_elem:
        return "未知時間"
    for attr in ('datetime', 'title', 'aria-label'):
        value = await time_elem.get_attribute(attr)
        if value and value.strip():
            return value.strip()
    text = (await time_elem.inner_text()).strip()
    return text or "未知時間"


async def fetch_trump_posts():
    wait_time = random.uniform(FETCH_WAIT_MIN_SECONDS, FETCH_WAIT_MAX_SECONDS)
    print(f"[{datetime.now()}] 隨機等待 {wait_time:.2f} 秒後開始抓取...")
    await asyncio.sleep(wait_time)

    posts = []
    seen_ids = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={'width': 1280, 'height': 2000},
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            print(f"[{datetime.now()}] 正在抓取: {TRUTH_URL}")
            await page.goto(TRUTH_URL, wait_until='networkidle', timeout=PAGE_GOTO_TIMEOUT_MS)
            await asyncio.sleep(PAGE_RENDER_WAIT_SECONDS)
            await page.evaluate(f"window.scrollBy(0, {SCROLL_PIXELS})")
            await asyncio.sleep(SCROLL_WAIT_SECONDS)

            articles = await page.query_selector_all('article, div[data-testid="status"]')
            print(f"找到 {len(articles)} 個潛在貼文元素")

            for idx, article in enumerate(articles):
                inner_text = await article.inner_text()
                if "Sponsored" in inner_text:
                    print(f"  article[{idx}] skip: sponsored")
                    continue

                id_link = await article.query_selector('a[href*="/posts/"]')
                if not id_link:
                    print(f"  article[{idx}] skip: no post link")
                    continue
                href = await id_link.get_attribute('href') or ""
                if "@realDonaldTrump" not in href:
                    print(f"  article[{idx}] skip: href not Trump ({href})")
                    continue
                match = re.search(r'/posts/(\d+)', href)
                if not match:
                    print(f"  article[{idx}] skip: id not matched ({href})")
                    continue
                post_id = match.group(1)
                seen_ids.add(post_id)

                content = await extract_post_content(article)
                if not content:
                    print(f"  article[{idx}] skip: empty content (post_id={post_id})")
                    continue

                timestamp = await extract_post_timestamp(article)

                posts.append({
                    'id': post_id,
                    'content': content,
                    'timestamp': timestamp,
                    'url': f"https://truthsocial.com{href}",
                })
        except PlaywrightTimeoutError as e:
            print(f"抓取逾時: {e}")
        except Exception as e:
            print(f"抓取錯誤: {type(e).__name__}: {e}")
        finally:
            await browser.close()

    unique_posts = {p['id']: p for p in posts}.values()
    sorted_posts = sorted(unique_posts, key=lambda x: x['id'], reverse=True)
    return sorted_posts, seen_ids


def get_last_ids():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, 'r') as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def save_ids(ids):
    os.makedirs(os.path.dirname(LAST_ID_FILE), exist_ok=True)
    with open(LAST_ID_FILE, 'w') as f:
        for pid in sorted(list(ids), reverse=True)[:LAST_ID_KEEP]:
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
        "請將以下貼文翻譯成繁體中文，只翻譯正文。"
        f"時間欄位必須原封不動輸出『{timestamp}』，不得改寫成『未提供』或其他文字，"
        "即使是相對時間（例如 2h）也照抄。\n\n"
        f"輸出格式固定為：\n貼文時間：{timestamp}\n貼文內容：<翻譯後內容>\n\n"
        f"原文：{content}"
    )


def run_hermes_command(cmd, action_label, timeout_seconds, retries):
    for attempt in range(1, retries + 1):
        print(f"{action_label}（第 {attempt}/{retries} 次，timeout={timeout_seconds}s）...")
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

        if attempt < retries:
            print(f"{HERMES_RETRY_DELAY_SECONDS} 秒後重試...")
            time.sleep(HERMES_RETRY_DELAY_SECONDS)

    return None


def normalize_hermes_output(output):
    if not output:
        return ""
    lines = [l for l in output.strip().splitlines() if not l.strip().startswith("session_id:")]
    return "\n".join(lines).strip()


def translate_with_hermes(content, timestamp):
    cmd = [
        HERMES_PATH,
        "chat",
        "-Q",
        "-q",
        build_translation_prompt(content, timestamp),
        "--provider",
        HERMES_PROVIDER,
        "--model",
        HERMES_MODEL,
    ]
    translated = run_hermes_command(
        cmd,
        f"hermes 翻譯貼文（時間：{timestamp}）",
        HERMES_TRANSLATE_TIMEOUT,
        HERMES_TRANSLATE_RETRIES,
    )
    return normalize_hermes_output(translated)


def load_telegram_bot_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token.strip()

    env_path = "/home/jimmy/.hermes/.env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    value = line.split("=", 1)[1].strip()
                    return value if value and value != "***" else None
    return None


def split_telegram_message(message, limit=TELEGRAM_CHUNK_LIMIT):
    """以換行/空白為優先切點，避免在句子或多位元組字元中間切開。"""
    if not message:
        return [""]
    chunks = []
    remaining = message
    while len(remaining) > limit:
        window = remaining[:limit]
        split_pos = window.rfind('\n')
        if split_pos <= 0:
            split_pos = window.rfind(' ')
        if split_pos <= 0:
            split_pos = limit
        chunk = remaining[:split_pos].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def send_telegram_chunk(token, chunk):
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": chunk,
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for attempt in range(1, TELEGRAM_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                response_json = json.loads(body)
                if response_json.get("ok"):
                    return True
                print(f"telegram 回應非 ok（第 {attempt}/{TELEGRAM_RETRIES} 次）: {body}")
        except Exception as e:
            print(f"❌ telegram 發送失敗（第 {attempt}/{TELEGRAM_RETRIES} 次）: {e}")

        if attempt < TELEGRAM_RETRIES:
            time.sleep(TELEGRAM_RETRY_DELAY_SECONDS)
    return False


def send_to_telegram(message):
    token = load_telegram_bot_token()
    if not token:
        print("❌ 找不到 TELEGRAM_BOT_TOKEN，無法直接發送 Telegram")
        return False

    chunks = split_telegram_message(message)
    for idx, chunk in enumerate(chunks, start=1):
        print(f"telegram 發送 chunk {idx}/{len(chunks)}（{len(chunk)} chars）")
        if not send_telegram_chunk(token, chunk):
            print(f"❌ chunk {idx}/{len(chunks)} 重試耗盡，放棄該貼文")
            return False
    return True


def process_with_hermes(content, timestamp):
    translated = translate_with_hermes(content, timestamp)
    if not translated:
        return False
    return send_to_telegram(translated)


async def main():
    posts, seen_ids = await fetch_trump_posts()
    if not seen_ids:
        print("未抓取到任何貼文。")
        return

    last_ids = get_last_ids()
    new_posts = [p for p in posts if p['id'] not in last_ids]

    # 所有看過的 ID 先暫記為已處理（含媒體/轉發無正文者，避免下次重複觸發）
    last_ids = last_ids | seen_ids

    if not new_posts:
        print("沒有新貼文需要翻譯。")
    else:
        print(f"發現 {len(new_posts)} 條新貼文需要翻譯！")
        for post in reversed(new_posts):  # 從舊到新處理
            # subprocess + HTTP 是同步阻塞，丟到執行緒避免卡住事件迴圈
            success = await asyncio.to_thread(
                process_with_hermes, post['content'], post['timestamp']
            )
            if not success:
                # 失敗就回退，讓下次有機會重試
                last_ids.discard(post['id'])
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
