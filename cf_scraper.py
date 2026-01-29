import cloudscraper
from bs4 import BeautifulSoup
import os
import hashlib
import time
import random

# --- CONFIGURATION ---
URL_LIST_FILE = "urls_retry.txt"
OUTPUT_DIR = "mock_internet/clean"

def clean_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "iframe", "header", "noscript"]):
        element.extract()
    text = soup.get_text(separator='\n')
    lines = (line.strip() for line in text.splitlines())
    return '\n'.join(chunk for chunk in lines if chunk)

def scrape_tough_urls():
    if not os.path.exists(URL_LIST_FILE):
        print(f"Please create '{URL_LIST_FILE}' with the URLs that returned 403.")
        return

    # Initialize CloudScraper (mimics a real browser)
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    with open(URL_LIST_FILE, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"--- Attempting to Scrape {len(urls)} Tough URLs ---")

    for i, url in enumerate(urls):
        try:
            print(f"[{i+1}/{len(urls)}] Scraping: {url[:50]}...")
            
            # Add a random delay to look human
            time.sleep(random.uniform(2, 5))
            
            response = scraper.get(url, timeout=15)
            
            if response.status_code != 200:
                print(f"   -> Still Failed (Status {response.status_code})")
                continue

            text_content = clean_text(response.text)
            
            # Save logic (same as before)
            domain = url.split("//")[-1].split("/")[0].replace("www.", "")
            url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
            filename = f"{domain}_{url_hash}.txt"
            filepath = os.path.join(OUTPUT_DIR, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"SOURCE_URL: {url}\n")
                f.write("-" * 50 + "\n")
                f.write(text_content)
                
            print(f"   -> Success! Saved to {filename}")
            
        except Exception as e:
            print(f"   -> Error: {e}")

if __name__ == "__main__":
    scrape_tough_urls()