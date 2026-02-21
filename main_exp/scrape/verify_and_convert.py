#!/usr/bin/env python3
"""
1. Verify that mock_internet files + manual-scrapes = total URLs in sources.txt.
2. Convert manual HTML scrapes to txt and place them in the correct domain folders.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent.resolve()
MAIN_EXP_DIR = SCRIPT_DIR.parent
SOURCES_FILE = SCRIPT_DIR / "sources.txt"
MOCK_INTERNET_DIR = MAIN_EXP_DIR / "mock_internet"
MANUAL_SCRAPES_DIR = SCRIPT_DIR / "manual-scrapes"
FAILED_URLS_FILE = SCRIPT_DIR / "failed_urls.json"

HTML_TO_URL_MAP = {
    "How to Fix Memory Leaks in React Applications - freecodecamp.html":
        "https://www.freecodecamp.org/news/fix-memory-leaks-in-react-apps/",
    "Troubleshooting _localhost won't connect_ _ InMotion Hosting.html":
        "https://www.inmotionhosting.com/support/website/error-numbers/localhost-refused-to-connect-error/",
    "Git detached head_ What is it & How to fix it.html":
        "https://kodekloud.com/blog/git-detached-head/",
    "How to Prevent Infinite Loops When Using useEffect() in ReactJS.html":
        "https://www.freecodecamp.org/news/prevent-infinite-loops-when-using-useeffect-in-reactjs/",
    "How to Fix Cross-Origin Errors — CORS Error Explained.html":
        "https://www.freecodecamp.org/news/how-to-fix-cross-origin-errors/",
    "How do I understand the out of memory errors in Node.js_ _ r_node.html":
        "https://www.reddit.com/r/node/comments/1j16j8b/how_do_i_understand_the_out_of_memory_errors_in/",
    "[Updated] How to Fix \u201cJavascript heap out of memory\u201d Error.html":
        "https://www.betterbugs.io/blog/javascript-heap-out-of-memory-error-fix",
    "Flutter pub get issues. _ r_flutterhelp.html":
        "https://www.reddit.com/r/flutterhelp/comments/1al48sh/flutter_pub_get_issues/",
    "Trouble with installing cocoapods _ Apple Developer Forums.html":
        "https://developer.apple.com/forums/thread/668456",
    "Why am I getting a CSRF Token missing when in fact it's there_ - Using Django _ Mystery Errors - Django Forum.html":
        "https://forum.djangoproject.com/t/why-am-i-getting-a-csrf-token-missing-when-in-fact-its-there/24911",
    "Cross Site Request Forgery protection _ Django documentation _ Django.html":
        "https://docs.djangoproject.com/en/6.0/ref/csrf/",
    "CSRF verification fails in unexpected situations - Using Django _ Mystery Errors - Django Forum.html":
        "https://forum.djangoproject.com/t/csrf-verification-fails-in-unexpected-situations/26509",
    "Docker_ Despite modifying server.port value, application is starting in 8080 only. Need to know why _ r_SpringBoot.html":
        "https://www.reddit.com/r/SpringBoot/comments/17jso57/docker_despite_modifying_serverport_value/",
    "Panic_ assignment to entry in nil map - Getting Help - Go Forum.html":
        "https://forum.golangbridge.org/t/panic-assignment-to-entry-in-nil-map/3332",
    "Panic_ assignment to entry in nil map - Docker Hub - Docker Community Forums.html":
        "https://forums.docker.com/t/panic-assignment-to-entry-in-nil-map/136806",
    "Map is apparently nil even though I already assigned to it - Getting Help _ Code Review - Go Forum.html":
        "https://forum.golangbridge.org/t/map-is-apparently-nil-even-though-i-already-assigned-to-it/28393",
    "References and Borrowing - The Rust Programming Language.html":
        "https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html",
    "Command _npm run build_ exited with 1 - Help - Vercel Community.html":
        "https://community.vercel.com/t/command-npm-run-build-exited-with-1/5407",
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def make_filename(url: str) -> str:
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{domain}_{url_hash}.txt"


def parse_sources(filepath: Path) -> list[dict]:
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


def clean_html_file(filepath: Path) -> str:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="latin-1") as f:
            content = f.read()

    soup = BeautifulSoup(content, "html.parser")
    for element in soup(
        ["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg", "form"]
    ):
        element.extract()

    for element in soup.find_all(
        attrs={"class": re.compile(r"(cookie|banner|popup|modal|sidebar|ad[s]?[-_])", re.I)}
    ):
        element.extract()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(chunk for chunk in lines if chunk)


def main():
    # -- Step 1: Parse sources and build (url, domain) pairs --
    domains = parse_sources(SOURCES_FILE)
    all_entries = []
    for domain in domains:
        slug = slugify(domain["name"])
        for url in domain["urls"]:
            all_entries.append({"url": url, "domain_name": domain["name"], "slug": slug})

    total_expected = len(all_entries)
    print(f"Total URL entries in sources.txt: {total_expected}")

    # -- Step 2: Check which entries already have txt files in mock_internet --
    entries_in_mock = []
    entries_missing = []
    for entry in all_entries:
        filename = make_filename(entry["url"])
        filepath = MOCK_INTERNET_DIR / entry["slug"] / "clean" / filename
        if filepath.exists():
            entries_in_mock.append(entry)
        else:
            entries_missing.append(entry)

    print(f"Files already in mock_internet: {len(entries_in_mock)}")

    # -- Step 3: Check manual-scrapes HTML files --
    html_files = list(MANUAL_SCRAPES_DIR.glob("*.html")) + list(MANUAL_SCRAPES_DIR.glob("*.htm"))
    print(f"HTML files in manual-scrapes: {len(html_files)}")

    urls_in_manual = set()
    unmatched_html = []
    for html_file in html_files:
        url = HTML_TO_URL_MAP.get(html_file.name)
        if url:
            urls_in_manual.add(url)
        else:
            unmatched_html.append(html_file.name)

    print(f"Manual scrapes matched to URLs: {len(urls_in_manual)}")

    # -- Step 4: Accounting --
    still_missing = [e for e in entries_missing if e["url"] not in urls_in_manual]

    print(f"\n=== ACCOUNTING ===")
    print(f"  Expected:                    {total_expected}")
    print(f"  In mock_internet:            {len(entries_in_mock)}")
    print(f"  Missing from mock_internet:  {len(entries_missing)}")
    print(f"  Covered by manual-scrapes:   {len(entries_missing) - len(still_missing)}")
    print(f"  STILL MISSING:               {len(still_missing)}")

    if unmatched_html:
        print(f"\n  Unmatched HTML files (no URL mapping):")
        for name in unmatched_html:
            print(f"    - {repr(name)}")

    if still_missing:
        print(f"\n  Missing URLs (not in mock_internet or manual-scrapes):")
        for entry in sorted(still_missing, key=lambda e: e["url"]):
            print(f"    [{entry['domain_name']}] {entry['url']}")
        return

    print(f"\nAll {total_expected} URL entries are accounted for!")

    # -- Step 5: Convert manual HTMLs to txt and place in correct domain folders --
    # Build url -> list of slugs mapping (a URL can belong to multiple domains)
    url_to_slugs = {}
    for entry in all_entries:
        url_to_slugs.setdefault(entry["url"], []).append(entry["slug"])

    print(f"\n=== CONVERTING MANUAL SCRAPES ===")
    for html_file in sorted(html_files):
        url = HTML_TO_URL_MAP.get(html_file.name)
        if not url:
            print(f"  SKIP (no mapping): {html_file.name}")
            continue

        filename = make_filename(url)
        slugs = url_to_slugs.get(url, [])
        if not slugs:
            print(f"  SKIP (URL not in sources): {url}")
            continue

        text_content = None
        for slug in slugs:
            target_dir = MOCK_INTERNET_DIR / slug / "clean"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / filename

            if target_path.exists():
                print(f"  SKIP (already exists): {slug}/clean/{filename}")
                continue

            if text_content is None:
                text_content = clean_html_file(html_file)
                if not text_content or len(text_content) < 50:
                    print(f"  WARNING: Very short content ({len(text_content or '')} chars) for {html_file.name}")

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(f"SOURCE_URL: {url}\n")
                f.write("-" * 50 + "\n")
                f.write(text_content)

            print(f"  OK: {html_file.name}")
            print(f"      -> {slug}/clean/{filename} ({len(text_content)} chars)")

    # -- Step 6: Final verification --
    print(f"\n=== FINAL VERIFICATION ===")
    final_count = 0
    for domain in domains:
        slug = slugify(domain["name"])
        clean_dir = MOCK_INTERNET_DIR / slug / "clean"
        domain_files = list(clean_dir.glob("*.txt")) if clean_dir.exists() else []
        expected = len(domain["urls"])
        actual = len(domain_files)
        status = "OK" if actual == expected else "MISMATCH"
        print(f"  {slug}: {actual}/{expected} {status}")
        final_count += actual

    print(f"\n  TOTAL: {final_count}/{total_expected}")
    if final_count == total_expected:
        print("  All URLs have corresponding txt files!")
    else:
        print(f"  STILL MISSING: {total_expected - final_count} files")


if __name__ == "__main__":
    main()
