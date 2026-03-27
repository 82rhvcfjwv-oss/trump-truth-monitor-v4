import asyncio
import json
import os
import re
import requests
import subprocess
import shlex
import random
from datetime import datetime
from playwright.async_api import async_playwright

# 配置
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
LAST_ID_FILE = '/home/jimmy/.openclaw/workspace/memory/trump_last_truth_v4.txt'
OPENCLAW_PATH = '/home/jimmy/.npm-global/bin/openclaw'
TELEGRAM_CHAT_ID = "1032617150"

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

def process_with_openclaw(content, timestamp):
    text_to_process = f"貼文時間：{timestamp}\n貼文內容：{content}"
    prompt_message = f"請將以下貼文翻譯成繁體中文，只需翻譯貼文正文，不需要翻譯 HTML 標籤與數字，翻譯完後立刻用 message send 發送到 chat id為{TELEGRAM_CHAT_ID}的Telegram頻道：{text_to_process}"
    
    cmd = [OPENCLAW_PATH, "agent", "--agent", "main", "--message", prompt_message]
    
    print(f"正在透過 openclaw 處理貼文（時間：{timestamp}）...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ openclaw 處理完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ openclaw 執行失敗: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ 發生未預期錯誤: {e}")
        return False

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
        success = process_with_openclaw(post['content'], post['timestamp'])
        if success:
            last_ids.add(post['id'])
        else:
            print(f"貼文 {post['id']} 處理失敗，跳過更新 ID")
    
    save_ids(last_ids)
    print("更新完成。")

if __name__ == "__main__":
    asyncio.run(main())
