import os
import json
import time
from datetime import datetime, timedelta
import re 

# --- Googleニュース (Selenium) 関連のインポート ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# --- Yahoo!ニュース (Requests + BeautifulSoup) 関連のインポート ---
import requests
from bs4 import BeautifulSoup

# --- gspread関連のインポート ---
import gspread

# --- MSNニュース (Selenium + BeautifulSoup) 関連のインポート ---
import pandas as pd # データ構造を一時的に作るのに使用


# 共通設定
KEYWORD = "日産"
# IMPORTANT: Replace with your actual Google Spreadsheet ID
# あなたのGoogleスプレッドシートIDに置き換えてください！
# 提供されたIDをここに設定
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
        print("ChromeDriver launched.")
    except Exception as e:
        print(f"Error: Failed to launch ChromeDriver. {e}")
        return []

    url = f"https://news.google.com/search?q={keyword}&hl=ja&gl=JP&ceid=JP:ja"
    print(f"Accessing URL (Google): {url}")
    
    articles_data = []
    try:
        driver.get(url)
        time.sleep(5)

        for _ in range(3): # Scroll down multiple times to load dynamic content
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        articles = driver.find_elements(By.TAG_NAME, "article")
        print(f"Number of article elements detected (Google): {len(articles)}")

        for i, article_elem in enumerate(articles):
            try:
                # Extract title, URL, published date, and source from each element
                title_tag = article_elem.find_element(By.CSS_SELECTOR, "a.JtKRv")
                date_tag = article_elem.find_element(By.CSS_SELECTOR, "time.hvbAAd")
                source_tag = article_elem.find_element(By.CSS_SELECTOR, "div.vr1PYe")

                title = title_tag.text.strip()
                date_utc_str = date_tag.get_attribute("datetime")
                url = title_tag.get_attribute("href")
                source = source_tag.text.strip() if source_tag else "N/A"

                if title and date_utc_str and url:
                    utc_dt = datetime.strptime(date_utc_str, "%Y-%m-%dT%H:%M:%SZ")
                    jst_dt = utc_dt + timedelta(hours=9) # Convert to JST
                    
                    # Format date as "YYYY/M/D HH:MM" (no zero-padding for month/day)
                    formatted_date = f"{jst_dt.year}/{jst_dt.month}/{jst_dt.day} {jst_dt.hour:02}:{jst_dt.minute:02}"

                    # Convert relative URLs to absolute URLs
                    full_url = "https://news.google.com" + url[1:] if url.startswith("./articles/") else url

                    articles_data.append({
                        'タイトル': title,
                        'URL': full_url,
                        '投稿日': formatted_date,
                        '引用元': source
                    })
            except Exception as e:
                # Uncomment the line below to see detailed errors in GitHub Actions logs for Google News
                # print(f"Error parsing Google article element {i}: {e}") 
                continue
        return articles_data
    except Exception as e:
        print(f"Unexpected error occurred while retrieving Google News: {e}")
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
    print(f"Accessing URL (Yahoo!): {url}")
    
    articles_data = []
    try:
        res = requests.get(url, headers=headers, timeout=10) 
        res.raise_for_status() 
        soup = BeautifulSoup(res.text, "html.parser")

        # --- Yahoo!ニュースの主要な記事ブロックを見つけるためのセレクタ強化 ---
        article_blocks = soup.find_all("li", attrs={"data-tn-screen": "results-item"})

        if not article_blocks:
            article_blocks = soup.find_all("li", class_="newsFeed_item")
            
        if not article_blocks:
            article_blocks = soup.find_all("div", class_=re.compile(r"sc-\w{6}-\d+\s+"))


        if not article_blocks:
            print("⚠️ Yahoo! News: No article blocks found. Please check selectors.")
            return []

        print(f"Number of article elements detected (Yahoo!): {len(article_blocks)}")

        for i, article in enumerate(article_blocks):
            title = ""
            link = ""
            date_str = ""
            formatted_date = ""
            source_text = "N/A"

            try:
                # --- タイトルとURLの抽出強化 ---
                title_link_tag = article.find("a", attrs={"data-cl-tab": "titleLink"})
                if title_link_tag:
                    title = title_link_tag.text.strip()
                    link = title_link_tag.get("href", "")
                else:
                    h_tag = article.find(["h2", "h3"])
                    if h_tag:
                        nested_link_tag = h_tag.find("a", href=True)
                        if nested_link_tag:
                            title = nested_link_tag.text.strip()
                            link = nested_link_tag.get("href", "")
                    
                    if not title and not link:
                        fallback_link_tag = article.find("a", href=True)
                        if fallback_link_tag and "news.yahoo.co.jp" in fallback_link_tag.get("href", ""):
                            if fallback_link_tag.text.strip() and len(fallback_link_tag.text.strip()) > 5:
                                title = fallback_link_tag.text.strip()
                                link = fallback_link_tag.get("href", "")

                # --- 投稿日の抽出強化 ---
                time_tag = article.find("time")
                if time_tag:
                    date_str = time_tag.text.strip()
                    date_str_clean = re.sub(r'\([月火水木金土日]\)', '', date_str).strip() 
                    try:
                        dt_obj = datetime.strptime(date_str_clean, "%Y/%m/%d %H:%M")
                        formatted_date = f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour:02}:{dt_obj.minute:02}"
                    except ValueError:
                        current_year = datetime.now().year
                        try:
                            dt_obj = datetime.strptime(f"{current_year}/{date_str_clean}", "%Y/%m/%d %H:%M")
                            formatted_date = f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour:02}:{dt_obj.minute:02}"
                        except ValueError:
                            formatted_date = date_str_clean 
                
                # --- 引用元の抽出強化 ---
                source_tag_data_by_text = article.find("div", attrs={"data-by-text": True})
                if source_tag_data_by_text:
                    source_text = source_tag_data_by_text["data-by-text"].strip()
                else: 
                    source_span = article.find("span", class_=re.compile(r"sc-\w{6}-\d+"))
                    if source_span:
                        source_text = source_span.text.strip()
                    else:
                        small_text_elements = article.find_all(lambda tag: tag.name in ['div', 'span', 'p', 'time'] and 'text-xs' in tag.get('class', []))
                        for elem in small_text_elements:
                            text = elem.text.strip()
                            if '記事' not in text and 'PR' not in text and '提供' not in text and len(text) < 30 and not re.match(r'\d{1,2}/\d{1,2}\(\w\)\s\d{1,2}:\d{2}', text):
                                source_text = text
                                break

                print(f"  Article {i}: Title='{title}', URL='{link}', Date(raw)='{date_str}', Date(fmt)='{formatted_date}', Source='{source_text}'")

                if not title or not link:
                    print(f"  Article {i}: Skipping as title or URL is empty.")
                    continue

                if "pr-label" in article.get("class", []) or "sponsored" in link.lower() or "advertisement" in link.lower():
                    print(f"  Article {i}: Skipping as it appears to be an ad/PR article.")
                    continue


                articles_data.append({
                    'タイトル': title,
                    'URL': link,
                    '投稿日': formatted_date,
                    '引用元': source_text
                })
                time.sleep(0.3) 
            except Exception as e:
                print(f"❌ Error parsing Yahoo! article element {i}: {e}") 
                continue
        return articles_data
    except requests.exceptions.RequestException as e:
        print(f"Error during request to Yahoo! News: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error occurred while retrieving Yahoo! News: {e}")
        return []


# --- MSNニュース取得関数 (Selenium + BeautifulSoup) ---
def get_msn_news(keyword: str) -> list[dict]:
    """
    SeleniumとBeautifulSoupを使用してMSNニュースから指定されたキーワードのニュース記事を取得します。
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
        print("MSN ChromeDriver launched.")
    except Exception as e:
        print(f"Error: Failed to launch MSN ChromeDriver. {e}")
        return []

    # ✅ 現在時刻（日本時間）- スクラブ時に動的に取得
    now_jst = datetime.utcnow() + timedelta(hours=9)

    search_url = f'https://www.bing.com/news/search?q={keyword}&qft=sortbydate%3d"1"&form=YFNR'
    print(f"Accessing URL (MSN): {search_url}")
    
    articles_data = []
    try:
        driver.get(search_url)
        time.sleep(5) # ページ読み込みを待つ

        # ページの最下部までスクロールして、より多くの記事を読み込む
        # MSNの場合、無限スクロールがある可能性を考慮して複数回実行
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # ✅ 各ニュース記事の情報を取得
        # `div.news-card` が個々の記事ブロックに対応すると仮定
        news_cards = soup.select('div.news-card')
        print(f"Number of article elements detected (MSN): {len(news_cards)}")

        for i, card in enumerate(news_cards):
            title = card.get("data-title", "").strip()
            url = card.get("data-url", "").strip()
            source = card.get("data-author", "").strip() # data-author を引用元として使用

            pub_time_obj = None # datetimeオブジェクトとして日付を保持
            pub_label = "" # 元のaria-labelの内容を保持

            pub_tag = card.find("span", attrs={"aria-label": True})
            if pub_tag and pub_tag.has_attr("aria-label"):
                pub_label = pub_tag["aria-label"].strip()

            # 🔽 相対時刻を絶対日時に変換し、指定フォーマットに整形
            if "分前" in pub_label:
                minutes_match = re.search(r"(\d+)", pub_label)
                if minutes_match:
                    minutes = int(minutes_match.group(1))
                    pub_time_obj = now_jst - timedelta(minutes=minutes)
            elif "時間前" in pub_label:
                hours_match = re.search(r"(\d+)", pub_label)
                if hours_match:
                    hours = int(hours_match.group(1))
                    pub_time_obj = now_jst - timedelta(hours=hours)
            elif "日前" in pub_label:
                days_match = re.search(r"(\d+)", pub_label)
                if days_match:
                    days = int(days_match.group(1))
                    pub_time_obj = now_jst - timedelta(days=days)
            else:
                # 相対時間ではない場合（例: "5月28日" や "2024/05/28" など）
                try:
                    # "月日"形式を想定（例: "5月28日"）
                    if re.match(r'\d+月\d+日', pub_label):
                        current_year = now_jst.year
                        date_str_with_year = f"{current_year}年{pub_label}"
                        pub_time_obj = datetime.strptime(date_str_with_year, "%Y年%m月%d日")
                    # "YYYY/M/D"形式などを想定
                    elif re.match(r'\d{4}/\d{1,2}/\d{1,2}', pub_label):
                        pub_time_obj = datetime.strptime(pub_label, "%Y/%m/%d")
                    # "HH:MM" (当日) など、MSNがどう表示するかによる
                    elif re.match(r'\d{1,2}:\d{2}', pub_label): 
                        time_part = datetime.strptime(pub_label, "%H:%M").time()
                        pub_time_obj = datetime.combine(now_jst.date(), time_part)
                    else:
                        pub_time_obj = None # 解析できない場合はNone
                except ValueError:
                    pub_time_obj = None

            # 指定されたフォーマット "YYYY/M/D H:MM" に整形
            # pub_time_objがNoneの場合、元のpub_labelを使用
            # %#m, %#d はゼロパディングなしの月日
            formatted_date_str = pub_time_obj.strftime("%Y/%#m/%#d %H:%M") if pub_time_obj else pub_label

            # Debug print statements for each extracted value
            print(f"  Article {i}: Title='{title}', URL='{url}', Date(raw)='{pub_label}', Date(fmt)='{formatted_date_str}', Source='{source}'")

            if title and url:
                articles_data.append({
                    'タイトル': title,
                    'URL': url,
                    '投稿日': formatted_date_str, 
                    '引用元': source 
                })
            else:
                print(f"  Article {i}: Skipping as title or URL is empty.")

        return articles_data
    except Exception as e:
        print(f"MSNニュース取得中に予期せぬエラーが発生しました: {e}")
        return []
    finally:
        if driver:
            driver.quit()


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

    if credentials_json_str:
        try:
            credentials = json.loads(credentials_json_str)
            print("Loaded credentials from GCP_SERVICE_ACCOUNT_KEY environment variable.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON format in GCP_SERVICE_ACCOUNT_KEY environment variable: {e}")
            return
    else:
        try:
            with open('credentials.json', 'r') as f:
                credentials = json.load(f)
            print("Loaded credentials from credentials.json file (for local execution).")
        except FileNotFoundError:
            print("❌ Error: GCP_SERVICE_ACCOUNT_KEY environment variable is not set, and credentials.json was not found.")
            print("Please ensure you are running this in GitHub Actions, or place credentials.json for local execution.")
            return
        except json.JSONDecodeError as e:
            print(f"❌ Error: Invalid format in credentials.json file: {e}")
            return
    
    if not credentials:
        print("Failed to obtain credentials. Skipping spreadsheet write operation.")
        return

    try:
        gc = gspread.service_account_from_dict(credentials)
        print("Google Sheets API authentication successful.")
        
        sh = gc.open_by_key(spreadsheet_id)
        print(f"Opened spreadsheet '{spreadsheet_id}'.")
        
        # ワークシートが存在しない場合は作成
        try:
            worksheet = sh.worksheet(worksheet_name)
            print(f"ワークシート '{worksheet_name}' を選択しました。")
        except gspread.exceptions.WorksheetNotFound:
            print(f"ワークシート '{worksheet_name}' が見つかりません。新規作成します。")
            # ヘッダー行を考慮して初期行数を設定
            worksheet = sh.add_worksheet(title=worksheet_name, rows="1", cols="4") 
            # ヘッダー行を書き込む
            worksheet.append_row(['タイトル', 'URL', '投稿日', '引用元'])
            print(f"ワークシート '{worksheet_name}' を作成し、ヘッダーを書き込みました。")

        existing_data = worksheet.get_all_values()
        
        existing_urls = set()
        if len(existing_data) > 1: # Skip header row
            for row in existing_data[1:]:
                if len(row) > 1: # Ensure row has at least 2 columns (for URL)
                    existing_urls.add(row[1]) 
        
        print(f"Existing worksheet '{worksheet_name}' has {len(existing_urls)} unique URLs.")

        data_to_append = []
        new_articles_count = 0

        try:
            # '投稿日'が 'YYYY/MM/DD HH:MM' 形式であることを前提
            sorted_articles = sorted(
                articles, 
                key=lambda x: datetime.strptime(x.get('投稿日', '1900/01/01 00:00'), "%Y/%m/%d %H:%M"), 
                reverse=True # Newest articles first
            )
        except Exception as e:
            print(f"Warning: Date format error, sorting may not be correct: {e}")
            sorted_articles = articles # Use unsorted articles if error occurs

        for article in sorted_articles:
            if article.get('URL') and article.get('URL') not in existing_urls:
                data_to_append.append([
                    article.get('タイトル', ''),
                    article.get('URL', ''),
                    article.get('投稿日', ''),
                    article.get('引用元', '')
                ])
                new_articles_count += 1
                existing_urls.add(article.get('URL')) 
            
        if data_to_append:
            worksheet.append_rows(data_to_append, value_input_option='USER_ENTERED')
            print(f"✅ Appended {new_articles_count} new news data entries to worksheet '{worksheet_name}'.")
        else:
            print(f"⚠️ No new news data found for worksheet '{worksheet_name}'.")
            
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"⚠️ Spreadsheet '{spreadsheet_id}' not found. Please check the ID.")
        print("Ensure the service account has access permission to the spreadsheet.")
    except gspread.exceptions.APIError as e:
        print(f"❌ Google Sheets API エラーが発生しました: {e}")
        print(f"API Error Details: {e.response.text if hasattr(e, 'response') else '詳細不明'}")
        print("サービスアカウントの権限、またはスプレッドシートの共有設定を確認してください。")
    except Exception as e:
        print(f"❌ スプレッドシートへの書き込み中に予期せぬエラーが発生しました: {e}")


if __name__ == "__main__":
    print("🚀 ニュース取得を開始します...")
    
    # --- Googleニュースの取得と書き込み ---
    print("\n--- Google News ---")
    google_news_articles = get_google_news_with_selenium(KEYWORD) 
    if google_news_articles:
        print(f"✨ Retrieved {len(google_news_articles)} news articles from Google News.")
        write_to_spreadsheet(google_news_articles, SPREADSHEET_ID, "Google") 
    else:
        print("🤔 Failed to retrieve Google News.")
    
    # --- Yahoo!ニュースの取得と書き込み ---
    print("\n--- Yahoo! News ---")
    yahoo_news_articles = get_yahoo_news_with_requests(KEYWORD)
    if yahoo_news_articles:
        print(f"✨ Retrieved {len(yahoo_news_articles)} news articles from Yahoo! News.")
        write_to_spreadsheet(yahoo_news_articles, SPREADSHEET_ID, "Yahoo") 
    else:
        print("🤔 Failed to retrieve Yahoo! News.")

    # --- MSNニュースの取得と書き込み ---
    print("\n--- MSN News ---")
    msn_news_articles = get_msn_news(KEYWORD)
    if msn_news_articles:
        print(f"✨ Retrieved {len(msn_news_articles)} news articles from MSN News.")
        write_to_spreadsheet(msn_news_articles, SPREADSHEET_ID, "MSN") # "MSN"という新しいシートに書き込み
    else:
        print("🤔 Failed to retrieve MSN News.")
    
    print("\n✅ All news retrieval and writing completed.")
