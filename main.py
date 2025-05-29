import os
import json
import time
from datetime import datetime, timedelta
import re # Regular expression module

# --- Google News (Selenium) related imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# --- Yahoo! News (Requests + BeautifulSoup) related imports ---
import requests
from bs4 import BeautifulSoup

# gspread related import
import gspread

# Common settings
KEYWORD = "日産"
# IMPORTANT: Replace with your actual Google Spreadsheet ID
SPREADSHEET_ID = "1RglATeTbLU1SqlXnNToJqhXLdNoHCdePldioKDQgU8" 


# --- Google News scraping function (Selenium) ---
def get_google_news_with_selenium(keyword: str) -> list[dict]:
    """
    Retrieves news articles for a specified keyword from Google News using Selenium.
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


# --- Yahoo! News scraping function (Requests + BeautifulSoup) ---
def get_yahoo_news_with_requests(keyword: str) -> list[dict]:
    """
    Retrieves news articles for a specified keyword from Yahoo! News using Requests and BeautifulSoup.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    
    # URL will be automatically encoded by requests
    url = f"https://news.yahoo.co.jp/search?p={keyword}&ei=utf-8&categories=domestic,world,business,it,science,life,local"
    print(f"Accessing URL (Yahoo!): {url}")
    
    articles_data = []
    try:
        res = requests.get(url, headers=headers, timeout=10) # Added timeout
        res.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(res.text, "html.parser")

        # Yahoo! News selectors change frequently. Trying multiple patterns to be more robust.
        # Prioritize elements that are likely actual news articles.
        
        # 1. Look for `li` elements with `data-tn-screen="results-item"`
        article_blocks = soup.find_all("li", attrs={"data-tn-screen": "results-item"})

        if not article_blocks:
            # 2. Fallback: Look for `li` elements with class `newsFeed_item` (might include non-news items)
            article_blocks = soup.find_all("li", class_="newsFeed_item") 

        if not article_blocks:
            # 3. Fallback: Broader search for elements that look like article blocks (less specific)
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
                # Title and Link: Best to find `a` tag with `data-cl-tab="titleLink"`
                title_link_tag = article.find("a", attrs={"data-cl-tab": "titleLink"})
                if title_link_tag:
                    title = title_link_tag.text.strip()
                    link = title_link_tag.get("href", "") # Use .get() for safe attribute access
                else:
                    # Fallback: Try a more general link within the article block
                    fallback_link_tag = article.find("a", href=True)
                    # Check if the link is a valid Yahoo! News article link and has some text that could be a title
                    if fallback_link_tag and "news.yahoo.co.jp" in fallback_link_tag.get("href", ""):
                        if fallback_link_tag.text.strip() and len(fallback_link_tag.text.strip()) > 5: # Assume minimum title length
                             title = fallback_link_tag.text.strip()
                             link = fallback_link_tag.get("href", "")

                # Published Date: Look directly for the `time` tag
                time_tag = article.find("time")
                if time_tag:
                    date_str = time_tag.text.strip()
                    date_str_clean = re.sub(r'\([月火水木金土日]\)', '', date_str).strip() # Remove day of the week in parentheses
                    try:
                        dt_obj = datetime.strptime(date_str_clean, "%Y/%m/%d %H:%M")
                        # Format date as "YYYY/M/D HH:MM" (no zero-padding for month/day)
                        formatted_date = f"{dt_obj.year}/{dt_obj.month}/{dt_obj.day} {dt_obj.hour:02}:{dt_obj.minute:02}"
                    except ValueError:
                        formatted_date = date_str_clean # Use cleaned string if date conversion fails
                
                # Source: Prioritize elements with `data-by-text` attribute
                source_tag_data_by_text = article.find("div", attrs={"data-by-text": True})
                if source_tag_data_by_text:
                    source_text = source_tag_data_by_text["data-by-text"].strip()
                else: 
                    # Fallback: Look for a span with a dynamically generated class within the article block
                    source_span = article.find("span", class_=re.compile(r"sc-\w{6}-\d+"))
                    if source_span:
                        source_text = source_span.text.strip()

                # Debug print statements for each extracted value (visible in GitHub Actions logs)
                print(f"  Article {i}: Title='{title}', URL='{link}', Date(raw)='{date_str}', Date(fmt)='{formatted_date}', Source='{source_text}'")

                # Skip if title or URL could not be extracted
                if not title or not link:
                    print(f"  Article {i}: Skipping as title or URL is empty.")
                    continue

                articles_data.append({
                    'タイトル': title,
                    'URL': link,
                    '投稿日': formatted_date,
                    '引用元': source_text
                })
                time.sleep(0.3) # Add a small delay to avoid continuous access
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


# --- Spreadsheet writing function ---
def write_to_spreadsheet(articles: list[dict], spreadsheet_id: str, worksheet_name: str):
    """
    Writes retrieved news article data to a Google Spreadsheet.
    Checks existing URLs and appends only new articles.
    Articles are sorted by publication date (newest first) before appending.

    Args:
        articles (list[dict]): List of news articles to write.
        spreadsheet_id (str): Google Spreadsheet ID to write to.
        worksheet_name (str): Name of the worksheet to write to.
    """
    credentials_json_str = os.environ.get('GCP_SERVICE_ACCOUNT_KEY')
    credentials = None

    # In GitHub Actions, GCP_SERVICE_ACCOUNT_KEY environment variable should be set.
    # For local debugging, it will attempt to load from 'credentials.json'.
    if credentials_json_str:
        try:
            credentials = json.loads(credentials_json_str)
            print("Loaded credentials from GCP_SERVICE_ACCOUNT_KEY environment variable.")
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON format in GCP_SERVICE_ACCOUNT_KEY environment variable: {e}")
            return
    else:
        # If environment variable is not set (e.g., during local execution), try to load from file
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
        
        worksheet = sh.worksheet(worksheet_name)
        print(f"Selected worksheet '{worksheet_name}'.")
        
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
            # Assuming '投稿日' (Published Date) is in 'YYYY/MM/DD HH:MM' format
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
                existing_urls.add(article.get('URL')) # Add to set to prevent future duplicates in this run
            
        if data_to_append:
            worksheet.append_rows(data_to_append, value_input_option='USER_ENTERED')
            print(f"✅ Appended {new_articles_count} new news data entries to worksheet '{worksheet_name}'.")
        else:
            print(f"⚠️ No new news data found for worksheet '{worksheet_name}'.")
            
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"⚠️ Spreadsheet '{spreadsheet_id}' not found. Please check the ID.")
        print("Ensure the service account has access permission to the spreadsheet.")
    except gspread.exceptions.APIError as e:
        print(f"❌ Google Sheets API error occurred: {e}")
        print(f"API Error Details: {e.response.text if hasattr(e, 'response') else 'Details unknown'}")
        print("Please check service account permissions or spreadsheet sharing settings.")
    except Exception as e:
        print(f"❌ Unexpected error occurred while writing to spreadsheet: {e}")


if __name__ == "__main__":
    print("🚀 Starting news retrieval...")
    
    # --- Retrieve and write Google News ---
    print("\n--- Google News ---")
    google_news_articles = get_google_news_with_selenium(KEYWORD) 
    if google_news_articles:
        print(f"✨ Retrieved {len(google_news_articles)} news articles from Google News.")
        write_to_spreadsheet(google_news_articles, SPREADSHEET_ID, "Google") # Write to "Google" sheet
    else:
        print("🤔 Failed to retrieve Google News.")
    
    # --- Retrieve and write Yahoo! News ---
    print("\n--- Yahoo! News ---")
    yahoo_news_articles = get_yahoo_news_with_requests(KEYWORD)
    if yahoo_news_articles:
        print(f"✨ Retrieved {len(yahoo_news_articles)} news articles from Yahoo! News.")
        write_to_spreadsheet(yahoo_news_articles, SPREADSHEET_ID, "Yahoo") # Write to "Yahoo" sheet
    else:
        print("🤔 Failed to retrieve Yahoo! News.")
    
    print("\n✅ All news retrieval and writing completed.")
