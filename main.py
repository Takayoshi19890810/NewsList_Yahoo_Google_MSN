import os
import json
import time
import re
import random
import requests
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import gspread

KEYWORD = "日産"
SPREADSHEET_ID = "1RglATeTbLU1SqlfXnNToJqhXLdNoHCdePldioKDQgU8"

paid_keywords_by_domain = {
    "default": [
        "この記事は有料", "プレミアム会員限定", "有料会員限定",
        "この記事は会員限定", "有料プラン", "続きを見るには",
        "この記事の続きを読むには"
    ],
    "kabutan.jp": [
        "このレポートは会員限定", "ログインが必要", "プレミアムサービス会員限定コンテンツ"
    ]
}

def format_datetime(dt_obj):
    return dt_obj.strftime("%Y/%m/%d %H:%M")

@@ -76,22 +65,148 @@
        pass
    return "取得不可"

def check_if_paid_article(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return "-"
        domain = re.search(r"https?://([^/]+)", url)
        domain = domain.group(1) if domain else "default"
        keywords = paid_keywords_by_domain.get(domain, paid_keywords_by_domain["default"])
        text = BeautifulSoup(response.text, "html.parser").get_text()
        for kw in keywords:
            if kw in text:
                return "有料"
        return "-"
    except:
        return "-"
def get_google_news_with_selenium(keyword: str) -> list[dict]:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    url = f"https://news.google.com/search?q={keyword}&hl=ja&gl=JP&ceid=JP:ja"
    driver.get(url)
    time.sleep(5)
    for _ in range(3):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    articles = soup.find_all("article")
    data = []
    for article in articles:
        try:
            a_tag = article.select_one("a.JtKRv")
            time_tag = article.select_one("time.hvbAAd")
            source_tag = article.select_one("div.vr1PYe")
            title = a_tag.text.strip()
            href = a_tag.get("href")
            url = "https://news.google.com" + href[1:] if href.startswith("./") else href
            dt = datetime.strptime(time_tag.get("datetime"), "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=9)
            pub_date = format_datetime(dt)
            source = source_tag.text.strip() if source_tag else "N/A"
            data.append({"タイトル": title, "URL": url, "投稿日": pub_date, "引用元": source})
        except:
            continue
    print(f"✅ Googleニュース件数: {len(data)} 件")
    return data

def get_yahoo_news_with_selenium(keyword: str) -> list[dict]:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    search_url = f"https://news.yahoo.co.jp/search?p={keyword}&ei=utf-8&categories=domestic,world,business,it,science,life,local"
    driver.get(search_url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()
    articles = soup.find_all("li", class_=re.compile("sc-1u4589e-0"))
    articles_data = []

    for article in articles:
        try:
            title_tag = article.find("div", class_=re.compile("sc-3ls169-0"))
            title = title_tag.text.strip() if title_tag else ""
            link_tag = article.find("a", href=True)
            url = link_tag["href"] if link_tag else ""
            time_tag = article.find("time")
            date_str = time_tag.text.strip() if time_tag else ""
            formatted_date = ""
            if date_str:
                date_str = re.sub(r'\([月火水木金土日]\)', '', date_str).strip()
                try:
                    dt_obj = datetime.strptime(date_str, "%Y/%m/%d %H:%M")
                    formatted_date = format_datetime(dt_obj)
                except:
                    formatted_date = date_str

            source_text = ""
            source_tag = article.find("div", class_="sc-n3vj8g-0 yoLqH")
            if source_tag:
                inner = source_tag.find("div", class_="sc-110wjhy-8 bsEjY")
                if inner and inner.span:
                    candidate = inner.span.text.strip()
                    if not candidate.isdigit():
                        source_text = candidate
            if not source_text or source_text.isdigit():
                alt_spans = article.find_all(["span", "div"], string=True)
                for s in alt_spans:
                    text = s.text.strip()
                    if 2 <= len(text) <= 20 and not text.isdigit() and re.search(r'[ぁ-んァ-ン一-龥A-Za-z]', text):
                        source_text = text
                        break

            if title and url:
                articles_data.append({
                    "タイトル": title,
                    "URL": url,
                    "投稿日": formatted_date if formatted_date else "取得不可",
                    "引用元": source_text
                })
        except:
            continue

    print(f"✅ Yahoo!ニュース件数: {len(articles_data)} 件")
    return articles_data

def get_msn_news_with_selenium(keyword: str) -> list[dict]:
    now = datetime.utcnow() + timedelta(hours=9)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    url = f"https://www.bing.com/news/search?q={keyword}&qft=sortbydate%3d'1'&form=YFNR"
    driver.get(url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()
    cards = soup.select("div.news-card")
    data = []

    for card in cards:
        try:
            title = card.get("data-title", "").strip()
            url = card.get("data-url", "").strip()
            source = card.get("data-author", "").strip()
            pub_label = ""
            pub_date = ""

            pub_tag = card.find("span", attrs={"aria-label": True})
            if pub_tag and pub_tag.has_attr("aria-label"):
                pub_label = pub_tag["aria-label"].strip().lower()

            pub_date = parse_relative_time(pub_label, now)

            if pub_date == "取得不可" and url:
                pub_date = get_last_modified_datetime(url)

            if title and url:
                data.append({
                    "タイトル": title,
                    "URL": url,
                    "投稿日": pub_date,
                    "引用元": source if source else "MSN"
                })
        except Exception as e:
            print(f"⚠️ MSN記事処理エラー: {e}")
            continue

    print(f"✅ MSNニュース件数: {len(data)} 件")
    return data

def write_to_spreadsheet(articles: list[dict], spreadsheet_id: str, worksheet_name: str):
    credentials_json_str = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
@@ -104,36 +219,13 @@
            try:
                worksheet = sh.worksheet(worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=worksheet_name, rows="1", cols="5")
                worksheet.append_row(['タイトル', 'URL', '投稿日', '引用元', '有料'])
                worksheet = sh.add_worksheet(title=worksheet_name, rows="1", cols="4")
                worksheet.append_row(['タイトル', 'URL', '投稿日', '引用元'])

            existing_data = worksheet.get_all_values()
            existing_urls = [row[1] for row in existing_data[1:] if len(row) > 1]

            # ✅ 一括で有料チェックを行って結果をE列にまとめる
            flags = []
            target_rows = []
            for i, row in enumerate(existing_data[1:], start=2):
                if len(row) >= 2:
                    url = row[1].strip()
                    if url:
                        flag = check_if_paid_article(url)
                        flags.append([flag])
                        target_rows.append(i)

            # ✅ 範囲指定で一括更新
            if flags:
                start_row = target_rows[0]
                end_row = target_rows[-1]
                worksheet.update(f"E{start_row}:E{end_row}", flags)

            # ✅ 新規データ追記
            new_data = []
            for a in articles:
                if a['URL'] not in existing_urls:
                    flag = check_if_paid_article(a['URL'])
                    new_data.append([a['タイトル'], a['URL'], a['投稿日'], a['引用元'], flag])
            existing_urls = set(row[1] for row in existing_data[1:] if len(row) > 1)

            new_data = [[a['タイトル'], a['URL'], a['投稿日'], a['引用元']] for a in articles if a['URL'] not in existing_urls]
            if new_data:
                worksheet.append_rows(new_data, value_input_option='USER_ENTERED')
                print(f"✅ {len(new_data)}件をスプレッドシートに追記しました。")
@@ -147,8 +239,17 @@
    raise RuntimeError("❌ Googleスプレッドシートへの書き込みに失敗しました（5回試行しても成功せず）")

if __name__ == "__main__":
    print("\n--- 有料記事チェック（既存ニュースすべて）---")
    for sheet_name in ["Yahoo", "Google", "MSN"]:
        print(f"▶ {sheet_name} シートを処理中...")
        write_to_spreadsheet([], SPREADSHEET_ID, sheet_name)
    print("✅ 全シートのチェック完了")
    print("\n--- Google News ---")
    google_news_articles = get_google_news_with_selenium(KEYWORD)
    if google_news_articles:
        write_to_spreadsheet(google_news_articles, SPREADSHEET_ID, "Google")

    print("\n--- Yahoo! News ---")
    yahoo_news_articles = get_yahoo_news_with_selenium(KEYWORD)
    if yahoo_news_articles:
        write_to_spreadsheet(yahoo_news_articles, SPREADSHEET_ID, "Yahoo")

    print("\n--- MSN News ---")
    msn_news_articles = get_msn_news_with_selenium(KEYWORD)
    if msn_news_articles:
        write_to_spreadsheet(msn_news_articles, SPREADSHEET_ID, "MSN")
