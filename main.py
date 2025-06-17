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

def write_to_spreadsheet(articles: list[dict], spreadsheet_id: str, worksheet_name: str):
    credentials_json_str = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
    credentials = json.loads(credentials_json_str) if credentials_json_str else json.load(open('credentials.json'))
    gc = gspread.service_account_from_dict(credentials)

    for attempt in range(5):
        try:
            sh = gc.open_by_key(spreadsheet_id)
            try:
                worksheet = sh.worksheet(worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                worksheet = sh.add_worksheet(title=worksheet_name, rows="1", cols="5")
                worksheet.append_row(['タイトル', 'URL', '投稿日', '引用元', '有料'])

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

            if new_data:
                worksheet.append_rows(new_data, value_input_option='USER_ENTERED')
                print(f"✅ {len(new_data)}件をスプレッドシートに追記しました。")
            else:
                print("⚠️ 追記すべき新しいデータはありません。")
            return
        except gspread.exceptions.APIError as e:
            print(f"⚠️ Google API Error (attempt {attempt + 1}/5): {e}")
            time.sleep(5 + random.random() * 5)

    raise RuntimeError("❌ Googleスプレッドシートへの書き込みに失敗しました（5回試行しても成功せず）")

if __name__ == "__main__":
    print("\n--- 有料記事チェック（既存ニュースすべて）---")
    for sheet_name in ["Yahoo", "Google", "MSN"]:
        print(f"▶ {sheet_name} シートを処理中...")
        write_to_spreadsheet([], SPREADSHEET_ID, sheet_name)
    print("✅ 全シートのチェック完了")
