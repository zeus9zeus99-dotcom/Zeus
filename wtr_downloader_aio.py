#!/usr/bin/env python3
"""
wtr_downloader_aio.py
سكربت لتنزيل فصول رواية من موقع WTR-Lab
باستخدام aiohttp + asyncio + BeautifulSoup
يدعم:
 - اكتشاف روابط الفصول تلقائيًا من الفهرس
 - أو استنتاج النمط (chapter-1, chapter-2 ...)
 - تنزيل متوازي آمن (يحد التوازي لتجنب الحظر)
 - حفظ كل فصل في ملف نصي داخل مجلد chapters/
"""

import argparse
import asyncio
import aiohttp
import aiofiles
import os
import re
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# إعدادات عامة
USER_AGENT = "Mozilla/5.0 (compatible; WTR-Downloader/1.0; +https://example.com/bot)"
COMMON_SELECTORS = [
    ".chapter-content", ".entry-content", ".novel-body", ".content", "article",
    "main", "div#content", "div.chapter", "div.chapter-body", "div[itemprop='articleBody']"
]

#------------------------------------------
# دوال مساعدة
#------------------------------------------

async def fetch_with_retry(session, url, max_retries=5, timeout=25):
    """طلب صفحة مع إعادة المحاولة عند الخطأ"""
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.text()
                elif resp.status == 404:
                    raise aiohttp.ClientResponseError(resp.request_info, resp.history,
                                                      status=404, message="Not found")
                else:
                    raise aiohttp.ClientError(f"HTTP {resp.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == max_retries:
                raise
            sleep_t = backoff + random.random()
            print(f"⚠️  خطأ مؤقت {e}, إعادة المحاولة بعد {sleep_t:.1f} ثانية...")
            await asyncio.sleep(sleep_t)
            backoff *= 2
    raise RuntimeError("فشل في fetch_with_retry بعد كل المحاولات")

def extract_chapter_links(html, base_url):
    """استخراج روابط الفصول من صفحة الفهرس"""
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.find_all("a", href=True)
    links = []
    patt = re.compile(r'chapter[-_/]?(\d+)', re.I)

    for a in anchors:
        href = a["href"]
        if patt.search(href):
            full = urljoin(base_url, href)
            links.append(full)
        txt = (a.get_text(" ", strip=True) or "").lower()
        if "start reading" in txt:
            full = urljoin(base_url, href)
            links.append(full)

    unique = list(dict.fromkeys(links))
    unique.sort(key=lambda u: int(patt.search(u).group(1)) if patt.search(u) else 0)
    return unique

def guess_chapter_pattern(start_link, base_url):
    """استنتاج نمط روابط الفصول مثل chapter-{}"""
    m = re.search(r'(.*/chapter[-_/]?)(\d+)(/?)$', start_link, re.I)
    if m:
        prefix = m.group(1)
        return urljoin(base_url, prefix + "{}")
    else:
        return base_url.rstrip('/') + "/chapter-{}"

def extract_chapter_content(html):
    """استخراج العنوان والنص"""
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find(["h1", "h2"])
    title = title_el.get_text(strip=True) if title_el else "Chapter"
    content = ""
    for sel in COMMON_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            content = el.get_text("\n\n", strip=True)
            break
    if not content:
        ps = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        content = "\n\n".join(ps)
    return title, content

#------------------------------------------
# التنزيل
#------------------------------------------

async def download_one(session, sem, url, idx, out_dir, delay):
    async with sem:
        try:
            html = await fetch_with_retry(session, url)
            title, content = extract_chapter_content(html)
            safe_title = re.sub(r'[\\/:*?"<>|]', '-', title)[:100]
            filename = os.path.join(out_dir, f"{idx:04d} - {safe_title}.txt")

            if not os.path.exists(out_dir):
                os.makedirs(out_dir)

            # تخطي إن كان الملف موجوداً مسبقاً
            if os.path.exists(filename):
                print(f"[SKIP] الفصل {idx} موجود مسبقاً")
                return

            async with aiofiles.open(filename, "w", encoding="utf-8") as f:
                await f.write(title + "\n\n" + content)
            print(f"[OK] {idx:04d} - {title}")
        except Exception as e:
            async with aiofiles.open(os.path.join(out_dir, "errors.log"), "a", encoding="utf-8") as ef:
                await ef.write(f"{idx:04d} {url} ERROR: {e}\n")
            print(f"[ERR] {idx:04d} ({e})")

        await asyncio.sleep(delay)

#------------------------------------------
# البرنامج الرئيسي
#------------------------------------------

async def main(args):
    url = args.url
    num = args.num
    concurrency = args.concurrency
    delay = args.delay
    out_dir = args.out

    headers = {"User-Agent": USER_AGENT}
    connector = aiohttp.TCPConnector(limit=concurrency * 2)
    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        print("🔍 يجلب صفحة الفهرس...")
        try:
            html = await fetch_with_retry(session, url)
        except Exception as e:
            print("❌ فشل في تحميل الفهرس:", e)
            return

        links = extract_chapter_links(html, url)

        if links:
            print(f"✅ عثر على {len(links)} رابط فصل، سيُحمّل أول {num}.")
            chapter_links = links[:num]
        else:
            print("⚠️ لم يجد روابط في الفهرس، يحاول استنتاج النمط...")
            start_link = url.rstrip('/') + "/chapter-1"
            pattern = guess_chapter_pattern(start_link, url)
            chapter_links = [pattern.format(i) for i in range(1, num + 1)]
            print(f"🔗 استُخدم النمط: {pattern}")

        tasks = []
        for idx, link in enumerate(chapter_links, 1):
            tasks.append(download_one(session, sem, link, idx, out_dir, delay))
        await asyncio.gather(*tasks)
        print("\n✅ اكتمل التنزيل.")

#------------------------------------------
# تشغيل البرنامج
#------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WTR-Lab novel downloader (aiohttp).")
    parser.add_argument("url", help="رابط صفحة الرواية (مثلاً https://wtr-lab.com/en/novel/7800/...)")
    parser.add_argument("-n", "--num", type=int, default=5, help="عدد الفصول التي سيتم تنزيلها")
    parser.add_argument("--concurrency", type=int, default=6, help="عدد الاتصالات المتزامنة")
    parser.add_argument("--delay", type=float, default=0.4, help="تأخير بعد كل طلب (بالثواني)")
    parser.add_argument("--out", default="chapters", help="مجلد الإخراج")
    args = parser.parse_args()

    asyncio.run(main(args))
