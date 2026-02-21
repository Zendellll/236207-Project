#!/usr/bin/env python3
"""
Robust scraper for the main experiment mock internet.

Reads sources.txt, creates directory structure, and scrapes all URLs
into domain-specific clean/ directories. Tracks failures for retry.
"""

import requests
import cloudscraper
from bs4 import BeautifulSoup
import os
import re
import hashlib
import time
import random
import json
import sys
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).parent.resolve()
SOURCES_FILE = SCRIPT_DIR / "sources.txt"
MOCK_INTERNET_DIR = SCRIPT_DIR / "mock_internet"
FAILED_LOG = SCRIPT_DIR / "failed_urls.json"
SCRAPE_LOG = SCRIPT_DIR / "scrape_log.json"

REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
POLITE_DELAY_RANGE = (1.0, 2.5)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def slugify(text: str) -> str:
    """Convert a domain name like 'React Native memory leak' to 'react-native-memory-leak'."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def parse_sources(filepath: Path) -> list[dict]:
    """
    Parse sources.txt into a list of domains, each with a name and URL list.
    Format: domain name on one line, followed by URLs, separated by blank lines.
    """
    domains = []
    current_domain = None
    current_urls = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                if current_domain and current_urls:
                    domains.append({"name": current_domain, "urls": current_urls})
                current_domain = None
                current_urls = []
                continue

            if line.startswith("http://") or line.startswith("https://"):
                current_urls.append(line)
            else:
                current_domain = line

    if current_domain and current_urls:
        domains.append({"name": current_domain, "urls": current_urls})

    return domains


def clean_text(html_content: str) -> str:
    """Extract readable text from HTML, removing boilerplate elements."""
    soup = BeautifulSoup(html_content, "html.parser")
    for element in soup(
        ["script", "style", "nav", "footer", "iframe", "header", "noscript", "svg", "form"]
    ):
        element.extract()

    for element in soup.find_all(attrs={"class": re.compile(r"(cookie|banner|popup|modal|sidebar|ad[s]?[-_])", re.I)}):
        element.extract()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    cleaned = "\n".join(chunk for chunk in lines if chunk)

    if len(cleaned) < 100:
        return ""
    return cleaned


def make_filename(url: str) -> str:
    """Generate a filename from the URL's domain + short hash."""
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{domain}_{url_hash}.txt"


def scrape_url_requests(url: str, session: requests.Session) -> tuple[str | None, str | None]:
    """Try scraping with requests. Returns (content, error)."""
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        resp = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            text = clean_text(resp.text)
            if text:
                return text, None
            return None, "Empty content after cleaning"
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return None, "Timeout"
    except requests.exceptions.ConnectionError as e:
        return None, f"ConnectionError: {e}"
    except Exception as e:
        return None, f"RequestsError: {e}"


def scrape_url_cloudscraper(url: str, scraper) -> tuple[str | None, str | None]:
    """Fallback: try scraping with cloudscraper for Cloudflare-protected sites."""
    try:
        resp = scraper.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            text = clean_text(resp.text)
            if text:
                return text, None
            return None, "Empty content after cleaning (cloudscraper)"
        return None, f"HTTP {resp.status_code} (cloudscraper)"
    except Exception as e:
        return None, f"CloudscraperError: {e}"


def scrape_single_url(url: str, session: requests.Session, cs_scraper) -> tuple[str | None, str | None]:
    """
    Attempt to scrape a URL with retries.
    First tries requests, then cloudscraper as fallback.
    Returns (content, error_or_None).
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        content, error = scrape_url_requests(url, session)
        if content:
            return content, None
        last_error = error

        if "403" in str(error) or "Cloudflare" in str(error).lower():
            break

        if attempt < MAX_RETRIES - 1:
            time.sleep(random.uniform(1, 3))

    content, error = scrape_url_cloudscraper(url, cs_scraper)
    if content:
        return content, None
    last_error = error

    return None, last_error


def create_directory_structure(domains: list[dict]) -> dict[str, Path]:
    """Create main_exp/mock_internet/<slug>/clean/ for each domain. Returns slug->path mapping."""
    slug_map = {}
    for domain in domains:
        slug = slugify(domain["name"])
        clean_dir = MOCK_INTERNET_DIR / slug / "clean"
        clean_dir.mkdir(parents=True, exist_ok=True)
        slug_map[domain["name"]] = clean_dir
    return slug_map


def load_existing_log() -> dict:
    """Load previous scrape log to support resumption."""
    if SCRAPE_LOG.exists():
        with open(SCRAPE_LOG, "r") as f:
            return json.load(f)
    return {}


def save_scrape_log(log: dict):
    with open(SCRAPE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def save_failed_urls(failed: list[dict]):
    with open(FAILED_LOG, "w") as f:
        json.dump(failed, f, indent=2)


def main():
    print(f"=== Main Experiment Scraper ===")
    print(f"Started at: {datetime.now().isoformat()}\n")

    domains = parse_sources(SOURCES_FILE)
    total_urls = sum(len(d["urls"]) for d in domains)
    print(f"Parsed {len(domains)} domains with {total_urls} total URLs\n")

    for d in domains:
        print(f"  - {d['name']} ({len(d['urls'])} URLs)")
    print()

    slug_map = create_directory_structure(domains)
    print(f"Directory structure created under {MOCK_INTERNET_DIR}\n")

    scrape_log = load_existing_log()

    session = requests.Session()
    session.headers.update({"Accept-Language": "en-US,en;q=0.9"})

    cs_scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "desktop": True}
    )

    failed_urls = []
    success_count = 0
    skip_count = 0
    fail_count = 0
    global_idx = 0

    for domain in domains:
        domain_name = domain["name"]
        clean_dir = slug_map[domain_name]
        slug = slugify(domain_name)

        print(f"\n--- Domain: {domain_name} ({slug}) ---")

        for url in domain["urls"]:
            global_idx += 1
            filename = make_filename(url)
            filepath = clean_dir / filename

            if url in scrape_log and scrape_log[url].get("status") == "success":
                if filepath.exists():
                    print(f"  [{global_idx}/{total_urls}] SKIP (already scraped): {url[:60]}...")
                    skip_count += 1
                    continue

            print(f"  [{global_idx}/{total_urls}] Scraping: {url[:70]}...")

            content, error = scrape_single_url(url, session, cs_scraper)

            if content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"SOURCE_URL: {url}\n")
                    f.write("-" * 50 + "\n")
                    f.write(content)

                scrape_log[url] = {
                    "status": "success",
                    "domain": domain_name,
                    "slug": slug,
                    "filename": filename,
                    "scraped_at": datetime.now().isoformat(),
                }
                success_count += 1
                print(f"    -> OK ({len(content)} chars) -> {filename}")
            else:
                scrape_log[url] = {
                    "status": "failed",
                    "domain": domain_name,
                    "slug": slug,
                    "error": error,
                    "attempted_at": datetime.now().isoformat(),
                }
                failed_urls.append({
                    "url": url,
                    "domain": domain_name,
                    "slug": slug,
                    "error": error,
                })
                fail_count += 1
                print(f"    -> FAILED: {error}")

            save_scrape_log(scrape_log)
            time.sleep(random.uniform(*POLITE_DELAY_RANGE))

    save_failed_urls(failed_urls)

    print(f"\n{'='*60}")
    print(f"=== SCRAPING COMPLETE ===")
    print(f"  Success: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Failed:  {fail_count}")
    print(f"  Total:   {total_urls}")
    print(f"{'='*60}")

    if failed_urls:
        print(f"\nFailed URLs saved to: {FAILED_LOG}")
        print("Failed URLs:")
        for f_entry in failed_urls:
            print(f"  - [{f_entry['domain']}] {f_entry['url']}")
            print(f"    Error: {f_entry['error']}")
    else:
        print("\nAll URLs scraped successfully!")

    print(f"\nScrape log saved to: {SCRAPE_LOG}")
    print(f"Finished at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
