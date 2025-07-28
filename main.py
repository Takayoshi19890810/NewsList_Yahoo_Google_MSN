import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials

KEYWORD = "日産"
SPREADSHEET_ID = "1RglATeTbLU1SqlfXnNToJqhXLdNoHCdePldioKDQgU8"
SHEET_NAME = datetime.now().strftime("%y%m%d")
BASE_SHEET = "Base"

def authorize_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    return gspread.authorize(credentials)

def prepare_output_sheet(spreadsheet):
    try:
        spreadsheet.duplicate_sheet(
            source_sheet_id=spreadsheet.worksheet(BASE_SHEET)._properties['sheetId'],
            new_sheet_name=SHEET_NAME
        )
    except:
        if SHEET_NAME in [s.title for s in spreadsheet.worksheets()]:
            spreadsheet.del_worksheet(spreadsheet.worksheet(SHEET_NAME))
        spreadsheet.duplicate_sheet(
            source_sheet_id=spreadsheet.worksheet(BASE_SHEET)._properties['sheetId'],
            new_sheet_name=SHEET_NAME
        )

def get_msn_news(keyword):
    url = f"https://www.msn.com/ja-jp/news/search?q={keyword}"
    return scrape_news_from_url(url, "MSN")

def get_yahoo_news(keyword):
    url = f"https://news.yahoo.co.jp/search?p={keyword}&ei=utf-8"
    return scrape_news_from_url(url, "Yahoo")

def get_google_news(keyword):
    url = f"https://www.google.com/search?q={keyword}&tbm=nws&hl=ja"
    return scrape_news_from_url(url, "Google")

def scrape_news_from_url(url, source_name):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    driver = webdriver.Chrome(options=options)
    driver.get(url)
    time.sleep(3)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    results = []
    date_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    if source_name == "MSN":
        items = soup.select("li")
        for li in items:
            title_tag = li.find("span")
            link_tag = li.find("a", href=True)
            if title_tag and link_tag:
                results.append([date_str, title_tag.text.strip(), link_tag["href"], "MSN"])

    elif source_name == "Yahoo":
        items = soup.select("div.newsFeed_item_title")
        for div in items:
            a_tag = div.find("a", href=True)
            if a_tag:
                results.append([date_str, a_tag.text.strip(), a_tag["href"], "Yahoo"])

    elif source_name == "Google":
        items = soup.select("div.dbsr")
        for div in items:
            a_tag = div.find("a", href=True)
            title_tag = div.select_one("div.JheGif.nDgy9d")
            if a_tag and title_tag:
                results.append([date_str, title_tag.text.strip(), a_tag["href"], "Google"])

    return results

def write_to_sheet(worksheet, data):
    for row in data:
        worksheet.append_row(row, value_input_option="USER_ENTERED")

def main():
    gc = authorize_google_sheets()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    prepare_output_sheet(spreadsheet)
    worksheet = spreadsheet.worksheet(SHEET_NAME)

    all_news = []
    all_news.extend(get_yahoo_news(KEYWORD))
    all_news.extend(get_google_news(KEYWORD))
    all_news.extend(get_msn_news(KEYWORD))

    write_to_sheet(worksheet, all_news)

if __name__ == "__main__":
    main()
