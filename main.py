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
# from urllib.parse import quote # URLエンコード用 (requestsが自動で処理する場合が多いが、念のため)

# gspread関連のインポート
import gspread

# 共通設定
KEYWORD = "日産"
SPREADSHEET_ID = "1RglATeTbLU1SqlfXnNToJqhXLdNoHCdePldioKDQgU8" # ご自身のスプレッドシートID


# --- Googleニュース取得関数 (既存) ---
def get_google_news_with_selenium(keyword: str) -> list[dict]:
    """
    Seleniumを使用してGoogleニュースから指定されたキーワードのニュース記事を取得します。
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

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
                    formatted_date = jst_dt.strftime("%Y/%#m/%#d %H:%M") # Windows用
                    # その他のOSの場合: formatted_date = jst_dt.strftime("%Y/%-m/%-d %H:%M")

                    full_url = "https://news.google.com" + url[1:] if url.startswith("./articles/") else url

                    articles_data.append({
                        'タイトル': title,
                        'URL': full_url,
                        '投稿日': formatted_date,
                        '引用元': source
                    })
            except Exception as e:
                # print(f"Google記事要素 {i} の解析中にエラーが発生しました: {e}")
                continue
        return articles_data
    except Exception as e:
        print(f"Googleニュース取得中に予期せぬエラーが発生しました: {e}")
        return []
    finally:
        if driver:
            driver.quit()


# --- Yahoo!ニュース取得関数 (新規追加) ---
def get_yahoo_news_with_requests(keyword: str) -> list[dict]:
    """
    RequestsとBeautifulSoupを使用してYahoo!ニュースから指定されたキーワードのニュース記事を取得します。
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"} # 最新のUser-Agentを推奨
    
    url = f"https://news.yahoo.co.jp/search?p={keyword}&ei=utf-8&categories=domestic,world,business,it,science,life,local"
    print(f"アクセスURL (Yahoo!): {url}")
    
    articles_data = []
    try:
        res = requests.get(url, headers=headers, timeout=10) # タイムアウト設定を追加
        res.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる
        soup = BeautifulSoup(res.text, "html.parser")

        # Yahoo!ニュースのセレクタは頻繁に変わる可能性があるため、注意深く確認
        # 主に li[data-tn-screen="results-item"] を使用
        article_blocks = soup.find_all("li", attrs={"data-tn-screen": "results-item"})

        if not article_blocks:
            # もし上記セレクタで取得できなければ、参考プログラムのセレクタも試す
            article_blocks = soup.find_all("li", class_=re.compile("sc-1u4589e-0"))
            if not article_blocks:
                print("⚠️ Yahoo!ニュース: 記事ブロックが見つかりませんでした。セレクタを確認してください。")
                return []

        print(f"検出された記事要素の数 (Yahoo!): {len(article_blocks)}")

        for i, article in enumerate(article_blocks):
            try:
                # タイトル: aタグで class="sc-3ls169-0..."
                title_tag = article.find("a", class_=re.compile("sc-3ls169-0.+"))
                title = title_tag.text.strip() if title_tag else ""

                link_tag = article.find("a", href=True)
                link = link_tag["href"] if link_tag else ""

                # 投稿日: timeタグ
                time_tag = article.find("time")
                date_str = time_tag.text.strip() if time_tag else ""

                # 投稿日時のフォーマット変更
                formatted_date = ""
                if date_str:
                    date_str = re.sub(r'\([月火水木金土日]\)', '', date_str).strip() # 括弧内の曜日を削除
                    try:
                        # 'YYYY/M/D H:MM' 形式に変換 (%m, %dはゼロ埋めなしにも対応)
                        dt_obj = datetime.strptime(date_str, "%Y/%m/%d %H:%M")
                        formatted_date = dt_obj.strftime("%Y/%#m/%#d %H:%M") # Windowsの場合
                        # その他のOSの場合: formatted_date = dt_obj.strftime("%Y/%-m/%-d %H:%M")
                    except ValueError:
                        # 変換できない場合は元の文字列をそのまま使用
                        formatted_date = date_str

                # ソースの抽出
                # data-by-text属性を持つdiv、または参考プログラムのセレクタ
                source_tag = article.find("div", attrs={"data-by-text": True})
                source_text = source_tag["data-by-text"].strip() if source_tag else "N/A"
                
                # もし上記で取れなければ、参考プログラムのセレクタも試す
                if source_text == "N/A" or not source_text:
                    source_tag_alt = article.find("div", class_="sc-n3vj8g-0") # yoLqH は動的クラス名なので削除
                    if source_tag_alt:
                        inner_source_tag_alt = source_tag_alt.find("span", class_=re.compile("sc-110wjhy-8.+")) # bsEjY も動的クラス名なので削除
                        if inner_source_tag_alt:
                            source_text = inner_source_tag_alt.text.strip() if inner_source_tag_alt else "N/A"


                if not title or not link:
                    # タイトルかURLが取得できなかった場合はスキップ
                    continue

                articles_data.append({
                    'タイトル': title,
                    'URL': link,
                    '投稿日': formatted_date,
                    '引用元': source_text
                })
                time.sleep(0.3) # 連続アクセスを避けるための遅延
            except Exception as e:
                # print(f"Yahoo記事要素 {i} の解析中にエラーが発生しました: {e}")
                continue
        return articles_data
    except requests.exceptions.RequestException as e:
        print(f"Yahoo!ニュースへのリクエスト中にエラーが発生しました: {e}")
        return []
    except Exception as e:
        print(f"Yahoo!ニュース取得中に予期せぬエラーが発生しました: {e}")
        return []


# --- スプレッドシート書き込み関数 (既存 + ソートロジック強化) ---
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

    if not credentials_json_str:
        print("GCP_SERVICE_ACCOUNT_KEY 環境変数が設定されていません。")
        print("ローカルデバッグの場合、credentials.json ファイルを直接読み込むか、環境変数に設定してください。")
        try:
            with open('credentials.json', 'r') as f:
                credentials = json.load(f)
            print("credentials.json から認証情報を読み込みました。")
        except Exception as e: 
            print(f"エラー: credentials.json の読み込みに失敗しました。{e}")
            return
    else:
        try:
            credentials = json.loads(credentials_json_str)
            print("GCP_SERVICE_ACCOUNT_KEY 環境変数から認証情報を読み込みました。")
        except json.JSONDecodeError as e:
            print(f"エラー: GCP_SERVICE_ACCOUNT_KEY 環境変数のJSON形式が不正です。{e}")
            return
    
    if not credentials:
        print("認証情報を取得できませんでした。スプレッドシートへの書き込みをスキップします。")
        return

    try:
        gc = gspread.service_account_from_dict(credentials)
        print("Google Sheets API 認証に成功しました。")
        
        sh = gc.open_by_key(spreadsheet_id)
        print(f"スプレッドシート '{spreadsheet_id}' を開きました。")
        
        worksheet = sh.worksheet(worksheet_name)
        print(f"ワークシート '{worksheet_name}' を選択しました。")
        
        existing_data = worksheet.get_all_values()
        
        existing_urls = set()
        if len(existing_data) > 1:
            for row in existing_data[1:]:
                if len(row) > 1: 
                    existing_urls.add(row[1]) 
        
        print(f"既存のワークシート'{worksheet_name}'には {len(existing_urls)} 件のユニークなURLがあります。")

        data_to_append = []
        new_articles_count = 0

        # 取得した記事を投稿日でソートする（最新のものが上に来るように降順）
        # '投稿日'は 'YYYY/MM/DD HH:MM' 形式なので、datetimeオブジェクトに変換してソート
        try:
            sorted_articles = sorted(
                articles, 
                key=lambda x: datetime.strptime(x.get('投稿日', '1900/01/01 00:00'), "%Y/%#m/%#d %H:%M"), 
                reverse=True
            )
        except Exception as e:
            print(f"警告: 日付フォーマットエラーのため、ソートが正しく行われない可能性があります: {e}")
            sorted_articles = articles # エラー時はソートしない

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
            print(f"✅ {new_articles_count}件の新しいニュースデータをワークシート'{worksheet_name}'に追記しました。")
        else:
            print(f"⚠️ ワークシート'{worksheet_name}'に新しいニュースデータはありませんでした。")
            
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"⚠️ スプレッドシート '{spreadsheet_id}' が見つかりません。IDを確認してください。")
        print("サービスアカウントにスプレッドシートへのアクセス権限が付与されていることを確認してください。")
    except gspread.exceptions.APIError as e:
        print(f"❌ Google Sheets API エラーが発生しました: {e}")
        print(f"APIエラー詳細: {e.response.text if hasattr(e, 'response') else '詳細不明'}")
        print("サービスアカウントの権限、またはスプレッドシートの共有設定を確認してください。")
    except Exception as e:
        print(f"❌ スプレッドシートへの書き込み中に予期せぬエラーが発生しました: {e}")


if __name__ == "__main__":
    print("🚀 ニュース取得を開始します...")
    
    # --- Googleニュースの取得と書き込み ---
    print("\n--- Googleニュース ---")
    google_news_articles = get_google_news_with_selenium(KEYWORD) 
    if google_news_articles:
        print(f"✨ Googleニュースから {len(google_news_articles)}件のニュースを取得しました。")
        write_to_spreadsheet(google_news_articles, SPREADSHEET_ID, "Google") # "Google"シートに書き込む
    else:
        print("🤔 Googleニュースが取得できませんでした。")
    
    # --- Yahoo!ニュースの取得と書き込み ---
    print("\n--- Yahoo!ニュース ---")
    yahoo_news_articles = get_yahoo_news_with_requests(KEYWORD)
    if yahoo_news_articles:
        print(f"✨ Yahoo!ニュースから {len(yahoo_news_articles)}件のニュースを取得しました。")
        write_to_spreadsheet(yahoo_news_articles, SPREADSHEET_ID, "Yahoo") # "Yahoo"シートに書き込む
    else:
        print("🤔 Yahoo!ニュースが取得できませんでした。")
    
    print("\n✅ 全ニュース取得・書き込み完了")
