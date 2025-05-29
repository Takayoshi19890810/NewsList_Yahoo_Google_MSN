import os
import json
import time
from datetime import datetime, timedelta
import re # 正規表現モジュール

# --- Googleニュース (Selenium) 関連のインポート ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# --- Yahoo!ニュース (Requests + BeautifulSoup) 関連のインポート ---
import requests
from bs4 import BeautifulSoup

# gspread関連のインポート
import gspread

# 共通設定
KEYWORD = "日産"
# ご自身のスプレッドシートIDに置き換えてください
SPREADSHEET_ID = "1RglATeTbLU1SqlfXnNToJqhXLdNoHCdePldioKDQgU8" 


# --- Googleニュース取得関数 (Selenium) ---
def get_google_news_with_selenium(keyword: str) -> list[dict]:
    """
    Seleniumを使用してGoogleニュースから指定されたキーワードのニュース記事を取得します。
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080") 

    driver = None
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("ChromeDriverを起動しました。")
    except Exception as e:
        print(f"エラー: ChromeDriverの起動に失敗しました。{e}")
        return []

    url = f"https://news.google.com/search?q={keyword}&hl=ja&gl=JP&ceid=JP:ja"
    print(f"アクセスURL (Google): {url}")
    
    articles_data = []
    try:
        driver.get(url)
        time.sleep(5)

        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        articles = driver.find_elements(By.TAG_NAME, "article")
        print(f"検出された記事要素の数 (Google): {len(articles)}")

        for i, article_elem in enumerate(articles):
            try:
                title_tag = article_elem.find_element(By.CSS_SELECTOR, "a.JtKRv")
                date_tag = article_elem.find_element(By.CSS_SELECTOR, "time.hvbAAd")
                source_tag = article_elem.find_element(By.CSS_SELECTOR, "div.vr1PYe")

                title = title_tag.text.strip()
                date_utc_str = date_tag.get_attribute("datetime")
                url = title_tag.get_attribute("href")
                source = source_tag.text.strip() if source_tag else "N/A"

                if title and date_utc_str and url:
                    utc_dt = datetime.strptime(date_utc_str, "%Y-%m-%dT%H:%M:%SZ")
                    jst_dt = utc_dt + timedelta(hours=9)
                    # Windowsの場合のゼロ埋めなしフォーマット (Python 3.6+ のみ)
                    formatted_date = jst_dt.strftime("%Y/%#m/%#d %H:%M") 
                    # その他のOS (Linux/macOS) の場合、%m, %d でゼロ埋めされるため、必要に応じて .lstrip('0') を適用
                    # 例: formatted_date = f"{jst_dt.year}/{jst_dt.month}/{jst_dt.day} {jst_dt.hour:02}:{jst_dt.minute:02}"

                    full_url = "https://news.google.com" + url[1:] if url.startswith("./articles/") else url

                    articles_data.append({
                        'タイトル': title,
                        'URL': full_url,
                        '投稿日': formatted_date,
                        '引用元': source
                    })
            except Exception as e:
                # GitHub Actionsのログに詳細を出力したい場合はコメント解除
                # print(f"Google記事要素 {i} の解析中にエラーが発生しました: {e}") 
                continue
        return articles_data
    except Exception as e:
        print(f"Googleニュース取得中に予期せぬエラーが発生しました: {e}")
        return []
    finally:
        if driver:
            driver.quit()


# --- Yahoo!ニュース取得関数 (Requests + BeautifulSoup) ---
def get_yahoo_news_with_requests(keyword: str) -> list[dict]:
    """
    RequestsとBeautifulSoupを使用してYahoo!ニュースから指定されたキーワードのニュース記事を取得します。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    
    url = f"https://news.yahoo.co.jp/search?p={keyword}&ei=utf-8&categories=domestic,world,business,it,science,life,local"
    print(f"アクセスURL (Yahoo!): {url}")
    
    articles_data = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status() 
        soup = BeautifulSoup(res.text, "html.parser")

        # Yahoo!ニュースのセレクタは頻繁に変わるため、より汎用的なものや複数パターンを試す
        article_blocks = soup.find_all("li", attrs={"data-tn-screen": "results-item"})

        if not article_blocks:
            article_blocks = soup.find_all("li", class_=re.compile(r"sc-\w{6}-\d+\s+")) 

        if not article_blocks:
            print("⚠️ Yahoo!ニュース: 記事ブロックが見つかりませんでした。セレクタを確認してください。")
            return []

        print(f"検出された記事要素の数 (Yahoo!): {len(article_blocks)}")

        for i, article in enumerate(article_blocks):
            title = ""
            link = ""
            date_str = ""
            formatted_date = ""
            source_text = "N/A"

            try:
                # タイトルとリンクは同一のaタグに格納されていることが多い
                title_link_tag = article.find("a", attrs={"data-cl-tab": "titleLink"})
                if title_link_tag:
                    title = title_link_tag.text.strip()
                    link = title_link_tag["href"]
                else: 
                    # フォールバック: 以前のセレクタパターン (クラス名が動的なため正規表現)
                    title_tag = article.find("a", class_=re.compile(r"sc-\w{6}-\d+")) # 例: sc-3ls169-0aのようなクラス名
                    if title_tag:
                        title = title_tag.text.strip()
                        link = title_tag["href"]

                # 投稿日: timeタグ
                time_tag = article.find("time")
                if time_tag:
                    date_str = time_tag.text.strip()
                    date_str_clean = re.sub(r'\([月火水木金土日]\)', '', date_str).strip() 
                    try:
                        dt_obj = datetime.strptime(date_str_clean, "%Y/%m/%d %H:%M")
                        # GitHub Actions (Linux) と Windows で %-m, %#m の挙動が異なる可能性を考慮し、
                        # より汎用的なf-string形式を推奨（必要に応じて）
                        formatted_date = f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour:02}:{dt_obj.minute:02}"
                    except ValueError:
                        formatted_date = date_str_clean 
                
                # 引用元: `data-by-text` 属性を持つ要素が最も信頼性が高い
                source_tag_data_by_text = article.find("div", attrs={"data-by-text": True})
                if source_tag_data_by_text:
                    source_text = source_tag_data_by_text["data-by-text"].strip()
                else: 
                    # フォールバック: 以前のセレクタパターン (クラス名が動的なため正規表現)
                    source_tag_alt1 = article.find("div", class_=re.compile(r"sc-\w{6}-\d+")) 
                    if source_tag_alt1:
                        inner_source_tag_alt1 = source_tag_alt1.find("span", class_=re.compile(r"sc-\w{6}-\d+"))
                        if inner_source_tag_alt1:
                            source_text = inner_source_tag_alt1.text.strip()

                # デバッグ用に取得した値を出力 (GitHub Actionsのログで確認)
                print(f"  記事 {i}: Title='{title}', URL='{link}', Date(raw)='{date_str}', Date(fmt)='{formatted_date}', Source='{source_text}'")

                if not title or not link:
                    print(f"  記事 {i}: タイトルまたはURLが空のためスキップします。")
                    continue

                articles_data.append({
                    'タイトル': title,
                    'URL': link,
                    '投稿日': formatted_date,
                    '引用元': source_text
                })
                time.sleep(0.3) 
            except Exception as e:
                print(f"❌ Yahoo記事要素 {i} の解析中にエラーが発生しました: {e}") 
                continue
        return articles_data
    except requests.exceptions.RequestException as e:
        print(f"Yahoo!ニュースへのリクエスト中にエラーが発生しました: {e}")
        return []
    except Exception as e:
        print(f"Yahoo!ニュース取得中に予期せぬエラーが発生しました: {e}")
        return []


# --- スプレッドシート書き込み関数 ---
def write_to_spreadsheet(articles: list[dict], spreadsheet_id: str, worksheet_name: str):
    """
    取得したニュース記事データをGoogleスプレッドシートに書き込みます。
    既存のURLをチェックし、新しいニュースのみを追記します。
    記事は投稿日の新しい順にソートされてから追記されます。

    Args:
        articles (list[dict]): 書き込むニュース記事のリスト。
        spreadsheet_id (str): 書き込み先のGoogleスプレッドシートID。
        worksheet_name (str): 書き込み先のワークシート名。
    """
    credentials_json_str = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
    credentials = None

    # GitHub Actions環境ではGCP_SERVICE_ACCOUNT_KEYが存在することを前提
    # ローカルデバッグの場合のみ credentials.json を試みる
    if credentials_json_str:
        try:
            credentials = json.loads(credentials_json_str)
            print("GCP_SERVICE_ACCOUNT_KEY 環境変数から認証情報を読み込みました。")
        except json.JSONDecodeError as e:
            print(f"エラー: GCP_SERVICE_ACCOUNT_KEY 環境変数のJSON形式が不正です。{e}")
            return
    else:
        # ローカル環境で環境変数が設定されていない場合のみ credentials.json を試す
        try:
            with open('credentials.json', 'r') as f:
                credentials = json.load(f)
            print("credentials.json から認証情報を読み込みました。（ローカル実行時）")
        except FileNotFoundError:
            print("❌ エラー: GCP_SERVICE_ACCOUNT_KEY 環境変数が設定されておらず、credentials.json も見つかりません。")
            print("GitHub Actionsで実行していることを確認するか、ローカル実行の場合は credentials.json を配置してください。")
            return
        except json.JSONDecodeError as e
