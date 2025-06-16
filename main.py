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
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import gspread

KEYWORD = "日産"
SPREADSHEET_ID = "1RglATeTbLU1SqlfXnNToJqhXLdNoHCdePldioKDQgU8"

def format_datetime(dt_obj):
    return dt_obj.strftime("%Y/%m/%d %H:%M")

def parse_relative_time(pub_label: str, base_time: datetime) -> str:
    pub_label = pub_label.strip().lower()
    try:
        if "分前" in pub_label or "minute" in pub_label:
            m = re.search(r"(\d+)", pub_label)
            if m:
                dt = base_time - timedelta(minutes=int(m.group(1)))
                return format_datetime(dt)
        elif "時間前" in pub_label or "hour" in pub_label:
            h = re.search(r"(\d+)", pub_label)
            if h:
                dt = base_time - timedelta(hours=int(h.group(1)))
                return format_datetime(dt)
        elif "日前" in pub_label or "day" in pub_label:
            d = re.search(r"(\d+)", pub_label)
            if d:
                dt = base_time - timedelta(days=int(d.group(1)))
                return format_datetime(dt)
        elif re.match(r'\d+月\d+日', pub_label):
            dt = datetime.strptime(f"{base_time.year}年{pub_label}", "%Y年%m月%d日")
            return format_datetime(dt)
        elif re.match(r'\d{4}/\d{1,2}/\d{1,2}', pub_label):
            dt = datetime.strptime(pub_label, "%Y/%m/%d")
            return format_datetime(dt)
        elif re.match(r'\d{1,2}:\d{2}', pub_label):
            t = datetime.strptime(pub_label, "%H:%M").time()
            dt = datetime.combine(base_time.date(), t)
            if dt > base_time:
                dt -= timedelta(days=1)
            return format_datetime(dt)
    except:
        pass
    return "取得不可"

def get_last_modified_datetime(url):
    try:
        response = requests.head(url, timeout=5)
        if 'Last-Modified' in response.headers:
            dt = parsedate_to_datetime(response.headers['Last-Modified'])
            jst = dt.astimezone(tz=timedelta(hours=9))
            return format_datetime(jst)
    except:
        pass
    return "取得不可"

def check_paywall_light(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        html = response.text.lower()
        if any(keyword in html for keyword in ["有料会員", "会員限定", "この記事は有料", "有料コンテンツ"]):
            return "有料"
    except:
        pass
    return ""

def check_paywall_with_selenium(url: str) -> str:
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.set_page_load_timeout(10)
        driver.get(url)
        time.sleep(3)
        page_text = driver.page_source.lower()
        driver.quit()
        if any(keyword in page_text for keyword in ["有料会員", "会員限定", "この記事は有料", "有料コンテンツ", "全文を読むには", "続きを読むには", "ログインしてください"]):
            return "有料"
    except Exception as e:
        print(f"⚠️ 有料判定失敗: {e}")
    return ""

def check_paywall(url: str) -> str:
    result = check_paywall_light(url)
    if not result:
        result = check_paywall_with_selenium(url)
    return result

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
            data.append({"タイトル": title, "URL": url, "投稿日": pub_date, "引用元": source, "有料": check_paywall(url)})
        except:
            continue
    print(f"✅ Googleニュース件数: {len(data)} 件")
    return data

# YahooとMSNの関数内も check_paywall(url) に置き換えるだけでOK（すでにその形式）

# 以下省略: 他の関数とメインブロックはそのままで動作します
