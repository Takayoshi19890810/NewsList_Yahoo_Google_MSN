import os
import json
import time
import re
from datetime import datetime
import gspread # Googleスプレッドシートのために追加

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

KEYWORD = "日産"
# ★ あなたのGoogleスプレッドシートIDを設定 ★
# スプレッドシートのURLから取得できます: https://docs.google.com/spreadsheets/d/1nphpu1q2cZuxJe-vYuOliw1azxqKKlzt6FFGNEJ76sw/edit#gid=0
# この場合、IDは "1nphpu1q2cZuxJe-vYuOliw1azxqKKlzt6FFGNEJ76sw" です。
GOOGLE_SPREADSHEET_ID = "1nphpu1q2cZuxJe-vYuOliw1azxqKKlzt6FFGNEJ76sw" # ここをあなたのスプレッドシートIDに置き換える

# サービスアカウントの認証情報ファイルへのパス (GitHub Actionsで一時的に作成)
SERVICE_ACCOUNT_KEY_FILE = "service_account_key.json" 

def format_datetime(dt_obj):
    return dt_obj.strftime("%Y/%m/%d %H:%M")

def get_yahoo_news_with_selenium(keyword: str) -> list[dict]:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
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
            source_tag_div = article.find("div", class_=re.compile(r"sc-\w+-\d+ yoLqH"))
            if source_tag_div:
                source_span = source_tag_div.find("span", class_=re.compile(r"sc-\w+-\d+ bsEjY"))
                if source_span:
                    candidate = source_span.text.strip()
                    if not candidate.isdigit():
                        source_text = candidate
            
            if not source_text or source_text.isdigit():
                all_text_elements = article.find_all(lambda tag: tag.name in ['span', 'div'] and tag.string is not None)
                for elem in all_text_elements:
                    text = elem.get_text(strip=True)
                    if 2 <= len(text) <= 20 and not text.isdigit() and re.search(r'[ぁ-んァ-ン一-龥A-Za-z]', text):
                        if text not in [title, date_str]:
                            source_text = text
                            break

            if title and url:
                articles_data.append({
                    "タイトル": title,
                    "URL": url,
                    "投稿日": formatted_date if formatted_date else "取得不可",
                    "引用元": source_text if source_text else "取得不可"
                })
        except Exception as e:
            print(f"⚠️ Yahoo!記事処理エラー: {e} (記事: {article.prettify()[:200]}...)")
            continue

    print(f"✅ Yahoo!ニュース件数: {len(articles_data)} 件")
    return articles_data

def write_to_google_sheet(articles: list[dict], spreadsheet_id: str, service_account_key_path: str):
    try:
        # サービスアカウントで認証 (認証情報のスコープを明示的に指定)
        gc = gspread.service_account(
            filename=service_account_key_path,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets', # スプレッドシートの読み書き
                'https://www.googleapis.com/auth/drive'         # Googleドライブへのアクセス（スプレッドシートを開くため）
            ]
        )
        spreadsheet = gc.open_by_id(spreadsheet_id)
        worksheet = spreadsheet.worksheet("Yahoo") # ★ あなたのシート名が「Yahoo」であることを確認 ★
        
        # ヘッダー行を読み込む（もしあれば）
        headers = worksheet.row_values(1)
        if not headers or headers[0] == '': # ヘッダーがなければ書き込む。最初のセルが空の場合も考慮。
            headers = ['タイトル', 'URL', '投稿日', '引用元']
            worksheet.append_row(headers)
        
        # 既存のURLを読み込み、重複を避ける
        existing_urls = set()
        all_rows = worksheet.get_all_records() # or worksheet.get_all_values()
        for row in all_rows:
            if 'URL' in row:
                existing_urls.add(row['URL'])

        # 新しいデータのみをフィルタリング
        new_rows = []
        for article in articles:
            # URLが空でないことと、既存のURLにないことを確認
            if article.get('URL') and article['URL'] not in existing_urls:
                new_rows.append([
                    article.get("タイトル", ""),
                    article.get("URL", ""),
                    article.get("投稿日", ""),
                    article.get("引用元", "")
                ])
        
        if new_rows:
            worksheet.append_rows(new_rows)
            print(f"✅ {len(new_rows)}件の新しい記事をGoogleスプレッドシートに追記しました。")
        else:
            print(f"⚠️ Googleスプレッドシートに追記すべき新しいデータはありません。")

    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ スプレッドシートID '{spreadsheet_id}' が見つかりません。IDが正しいか、サービスアカウントに共有されているか確認してください。")
    except gspread.exceptions.APIError as e:
        print(f"❌ Google Sheets APIエラーが発生しました: {e}. APIが有効になっているか、サービスアカウントの権限が適切か確認してください。")
    except Exception as e:
        print(f"❌ Googleスプレッドシートへの書き込み中に予期せぬエラーが発生しました: {e}")

if __name__ == "__main__":
    print("\n--- Yahoo! News ---")
    yahoo_news_articles = get_yahoo_news_with_selenium(KEYWORD)
    
    if yahoo_news_articles:
        # GitHub ActionsのシークレットからサービスアカウントキーのJSON文字列を取得し、ファイルとして保存
        gcp_service_account_key_json = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
        if gcp_service_account_key_json:
            with open(SERVICE_ACCOUNT_KEY_FILE, 'w') as f:
                f.write(gcp_service_account_key_json)
            
            write_to_google_sheet(yahoo_news_articles, GOOGLE_SPREADSHEET_ID, SERVICE_ACCOUNT_KEY_FILE)
            
            # 認証情報ファイルを削除 (セキュリティのため)
            if os.path.exists(SERVICE_ACCOUNT_KEY_FILE):
                os.remove(SERVICE_ACCOUNT_KEY_FILE)
        else:
            print("❌ GCP_SERVICE_ACCOUNT_KEY がGitHub Actionsの環境変数に設定されていません。")
    else:
        print("⚠️ 取得されたYahoo!ニュース記事がありません。")
