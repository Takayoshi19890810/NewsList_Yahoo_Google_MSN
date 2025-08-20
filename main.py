# main.py
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

# Sheets
import gspread
from google.oauth2.service_account import Credentials

# （任意）Geminiでタイトル分類
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except Exception:
    HAS_GEMINI = False

# ====== 基本設定 ======
JST = timezone(timedelta(hours=9))
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/119.0.0.0 Safari/537.36"
    )
}

NEWS_KEYWORD = os.getenv("NEWS_KEYWORD", "日産")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON_PATH", "credentials.json")

# 日次ウィンドウ：昨日15:00〜今日14:59
WINDOW_START_HOUR = 15
USE_TIME_WINDOW   = int(os.getenv("USE_TIME_WINDOW", "1"))  # 0:無効 1:有効
END_INCLUSIVE     = int(os.getenv("END_INCLUSIVE", "1"))    # 1:上端含む（<=）
INCLUDE_NO_DATE   = int(os.getenv("INCLUDE_NO_DATE", "1"))  # 1:投稿日なしでも残す

# スクロール強度
SCROLLS_GOOGLE = int(os.getenv("SCROLLS_GOOGLE", "4"))
SCROLLS_YAHOO  = int(os.getenv("SCROLLS_YAHOO", "4"))
SCROLL_SLEEP   = float(os.getenv("SCROLL_SLEEP", "1.2"))

# Yahoo pickup 解決不可時の採用可否
ALLOW_PICKUP_FALLBACK = int(os.getenv("ALLOW_PICKUP_FALLBACK", "1"))

# Selenium 起動モード
USE_WDM = int(os.getenv("USE_WDM", "1"))  # 1: webdriver-manager 使用 / 0: Selenium Manager に任せる

# どのソースを使うか
ENABLE_GOOGLE = int(os.getenv("ENABLE_GOOGLE", "1"))
ENABLE_YAHOO  = int(os.getenv("ENABLE_YAHOO", "1"))
ENABLE_MSN    = int(os.getenv("ENABLE_MSN", "0"))  # 必要なら1

# ====== 共通ユーティリティ ======
def now_jst():
    return datetime.now(JST)

def fmt_jst(dt: datetime):
    return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")

def compute_window():
    now = now_jst()
    today_1500 = now.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    if now < today_1500:
        start = today_1500 - timedelta(days=1)
        end   = today_1500 + timedelta(hours=23, minutes=59, seconds=59) - timedelta(days=1)
    else:
        start = today_1500
        end   = today_1500 + timedelta(hours=23, minutes=59, seconds=59)

    if not END_INCLUSIVE:
        end = end - timedelta(seconds=1)

    sheet_name = start.strftime("%y%m%d")
    return start, end, sheet_name

def in_window_str(pub_str: str, start: datetime, end: datetime) -> bool:
    if not USE_TIME_WINDOW:
        return True
    if not pub_str:
        return bool(INCLUDE_NO_DATE)
    try:
        dt = datetime.strptime(pub_str, "%Y/%m/%d %H:%M").replace(tzinfo=JST)
    except Exception:
        return bool(INCLUDE_NO_DATE)
    return start <= dt <= end

def head_last_modified_jst(url: str) -> str:
    try:
        r = requests.head(url, headers=UA, timeout=10, allow_redirects=True)
        lm = r.headers.get("Last-Modified")
        if lm:
            dt = parsedate_to_datetime(lm).astimezone(JST)
            return fmt_jst(dt)
    except Exception:
        pass
    return ""

def fetch_html(url: str, timeout=15):
    try:
        res = requests.get(url, headers=UA, timeout=timeout)
        res.raise_for_status()
        return res.text
    except Exception:
        return ""

# ====== Selenium 起動 ======
def get_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,2000")
    options.add_argument("--lang=ja-JP")

    if USE_WDM:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        # Selenium 4.10+ は Selenium Manager が自動解決
        driver = webdriver.Chrome(options=options)

    return driver

def smooth_scroll(driver, times=4, sleep=1.2):
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(sleep)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

# ====== Google News（Selenium・スクロール）======
def fetch_google_news(keyword: str):
    url = f"https://news.google.com/search?q={keyword}&hl=ja&gl=JP&ceid=JP:ja"
    items = []
    seen = set()
    driver = None
    try:
        driver = get_driver()
        driver.get(url)
        smooth_scroll(driver, SCROLLS_GOOGLE, SCROLL_SLEEP)
        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/articles/" not in href:
                continue
            if href.startswith("./"):
                full = "https://news.google.com" + href[1:]
            elif href.startswith("/"):
                full = "https://news.google.com" + href
            else:
                full = href

            title = a.get_text(strip=True)

            pub = ""
            parent = a.find_parent("article")
            if parent:
                t = parent.find("time")
                if t and t.has_attr("datetime"):
                    try:
                        dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00")).astimezone(JST)
                        pub = fmt_jst(dt)
                    except Exception:
                        pass

            final_url = ""
            try:
                r = requests.get(full, headers=UA, timeout=10, allow_redirects=True)
                final_url = r.url
            except Exception:
                final_url = full

            if not pub:
                pub = head_last_modified_jst(final_url)

            if final_url in seen:
                continue
            seen.add(final_url)

            if title:
                items.append(("Google", final_url, title, pub or "", ""))

            time.sleep(0.08)

    except Exception:
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()
    return items

# ====== Yahoo!ニュース（Selenium・スクロール）======
def resolve_yahoo_article_url(html: str, url: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        og = soup.find("meta", attrs={"property": "og:url", "content": True})
        if og and og["content"].startswith("http"):
            return og["content"]
        link = soup.find("link", attrs={"rel": "canonical", "href": True})
        if link and link["href"].startswith("http"):
            return link["href"]
    except Exception:
        pass
    return url

def extract_yahoo_datetime_from_article(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    m = soup.find("meta", attrs={"itemprop": "datePublished", "content": True})
    if m:
        try:
            dt = datetime.fromisoformat(m["content"].replace("Z", "+00:00")).astimezone(JST)
            return fmt_jst(dt)
        except Exception:
            pass
    t = soup.find("time")
    if t:
        if t.has_attr("datetime"):
            try:
                dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00")).astimezone(JST)
                return fmt_jst(dt)
            except Exception:
                pass
    return ""

def extract_yahoo_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title", "content": True})
        if og:
            title = og["content"].strip()
    if not title:
        title = (soup.title.get_text(strip=True) if soup.title else "").strip()
    return title

def fetch_yahoo_news(keyword: str):
    url = (
        "https://news.yahoo.co.jp/search"
        f"?p={keyword}&ei=utf-8&ts=0&st=n&sr=1&sk=all"
        "&categories=domestic,world,business,it,science,life,local"
    )
    items = []
    seen = set()
    driver = None
    try:
        driver = get_driver()
        driver.get(url)
        smooth_scroll(driver, SCROLLS_YAHOO, SCROLL_SLEEP)
        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")

        cand = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://news.yahoo.co.jp" + href
            if "news.yahoo.co.jp/articles/" in href or "news.yahoo.co.jp/pickup/" in href:
                cand.append(href)

        for u in cand:
            if u in seen:
                continue
            seen.add(u)

            html0 = fetch_html(u)
            art_url = resolve_yahoo_article_url(html0, u)

            html1 = html0 if art_url == u else fetch_html(art_url)
            if not html1:
                if ALLOW_PICKUP_FALLBACK:
                    items.append(("Yahoo", u, "", "", ""))
                continue

            title = extract_yahoo_title(html1)
            pub = extract_yahoo_datetime_from_article(html1)
            if not pub:
                pub = head_last_modified_jst(art_url)

            if not title:
                soup1 = BeautifulSoup(html1, "lxml")
                og = soup1.find("meta", attrs={"property": "og:title", "content": True})
                if og:
                    title = og["content"].strip()

            final = art_url or u
            items.append(("Yahoo", final, title, pub or "", ""))

            time.sleep(0.1)

    except Exception:
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()
    return items

# ====== （任意）MSN（簡易・既定OFF）======
def fetch_msn_news(keyword: str):
    items = []
    try:
        q = requests.utils.quote(keyword)
        url = f"https://www.msn.com/ja-jp/news/search?q={q}"
        html = fetch_html(url)
        soup = BeautifulSoup(html, "lxml")
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            if "msn.com" in href and "/news/" in href:
                title = a.get_text(strip=True)
                if not title:
                    continue
                final = href
                if final in seen:
                    continue
                seen.add(final)
                pub = head_last_modified_jst(final)
                items.append(("MSN", final, title, pub or "", ""))
                if len(items) > 60:
                    break
    except Exception:
        traceback.print_exc()
    return items

# ====== Google Sheets ======
def open_sheet(spreadsheet_id: str):
    # 認証JSONの書き出し（環境変数→ファイル）
    path = os.getenv("GOOGLE_CREDENTIALS_JSON_PATH", "credentials.json")
    if not os.path.exists(path):
        blob = os.getenv("GOOGLE_CREDENTIALS", "") or os.getenv("GCP_SERVICE_ACCOUNT_KEY", "")
        if blob:
            with open(path, "w", encoding="utf-8") as f:
                f.write(blob)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    return sh

def upsert_sheet(sh, sheet_name: str, rows: list):
    headers = ["ソース", "URL", "タイトル", "投稿日", "引用元"]
    try:
        ws = sh.worksheet(sheet_name)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=sheet_name, rows="5000", cols=str(len(headers)))
    ws.update("A1:E1", [headers])
    if rows:
        ws.update(f"A2:E{len(rows)+1}", rows)

# ====== タイトル分類（任意・未使用）======
def classify_titles_gemini_batched(titles: list):
    if not HAS_GEMINI:
        return [("", "")] * len(titles)
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return [("", "")] * len(titles)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    res = []
    prompt = (
        "以下のニュースタイトルを、①ポジ/ネガ/ニュートラル と ②カテゴリ（会社/車/技術/社会/スポーツ/エンタメ/その他）で出力。\n"
        "出力は TSV（タイトル\t感情\tカテゴリ）。\n"
    )
    chunk = 30
    for i in range(0, len(titles), chunk):
        part = titles[i:i+chunk]
        text = prompt + "\n".join([f"- {t}" for t in part])
        try:
            r = model.generate_content(text)
            _ = r.text.strip().splitlines()
            for _ in part:
                res.append(("", ""))
        except Exception:
            for _ in part:
                res.append(("", ""))
    return res[:len(titles)]

# ====== 集約・実行 ======
def main():
    print(f"🔎 キーワード: {NEWS_KEYWORD}")
    print(f"📄 SPREADSHEET_ID: {SPREADSHEET_ID}")

    start, end, sheet_name = compute_window()
    print(f"⏱ 期間: {fmt_jst(start)} 〜 {fmt_jst(end)}  → シート名: {sheet_name}")

    all_items = []

    if ENABLE_GOOGLE:
        google_items = fetch_google_news(NEWS_KEYWORD)
        print(f"Google raw: {len(google_items)}")
        all_items.extend(google_items)

    if ENABLE_YAHOO:
        yahoo_items = fetch_yahoo_news(NEWS_KEYWORD)
        print(f"Yahoo raw: {len(yahoo_items)}")
        all_items.extend(yahoo_items)

    if ENABLE_MSN:
        msn_items = fetch_msn_news(NEWS_KEYWORD)
        print(f"MSN raw: {len(msn_items)}")
        all_items.extend(msn_items)

    # 重複URL除去 & 最良pub採用
    uniq = {}
    for src, url, title, pub, origin in all_items:
        if url not in uniq:
            uniq[url] = [src, url, title, pub, origin]
        else:
            if not uniq[url][3] and pub:
                uniq[url] = [src, url, title, pub, origin]

    rows = []
    raw_count = len(uniq)
    for v in uniq.values():
        if in_window_str(v[3], start, end):
            rows.append(v)

    print(f"📦 重複除去後: {raw_count} → 時間フィルタ後: {len(rows)}")

    # Sheets 出力
    sh = open_sheet(SPREADSHEET_ID)
    upsert_sheet(sh, sheet_name, rows)
    print(f"✅ 書き込み完了: {sheet_name} ({len(rows)}件)")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ エラー:", e)
        traceback.print_exc()
        raise
