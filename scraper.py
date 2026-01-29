import requests
from bs4 import BeautifulSoup
import os
import hashlib
import time

# --- CONFIGURATION ---
URL_LIST_FILE = "urls.txt"
OUTPUT_DIR = "mock_internet/clean"

def clean_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    # Remove junk
    for element in soup(["script", "style", "nav", "footer", "iframe", "header"]):
        element.extract()
    
    text = soup.get_text(separator='\n')
    # Collapse multiple newlines
    lines = (line.strip() for line in text.splitlines())
    return '\n'.join(chunk for chunk in lines if chunk)

def scrape_urls():
    if not os.path.exists(URL_LIST_FILE):
        print(f"Error: {URL_LIST_FILE} not found. Please create it and paste your URLs there.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    with open(URL_LIST_FILE, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"--- Starting Scraping of {len(urls)} URLs ---")

    for i, url in enumerate(urls):
        try:
            print(f"[{i+1}/{len(urls)}] Scraping: {url[:50]}...")
            # Headers to mimic browser
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"   -> Failed (Status {response.status_code})")
                continue

            text_content = clean_text(response.text)
            
            # Create filename from domain + hash
            domain = url.split("//")[-1].split("/")[0].replace("www.", "")
            url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
            filename = f"{domain}_{url_hash}.txt"
            
            filepath = os.path.join(OUTPUT_DIR, filename)
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"SOURCE_URL: {url}\n")
                f.write("-" * 50 + "\n")
                f.write(text_content)
            
            time.sleep(1) # Be polite
            
        except Exception as e:
            print(f"   -> Error: {e}")

    print(f"\n--- Done! Files saved to {OUTPUT_DIR} ---")

if __name__ == "__main__":
    scrape_urls()