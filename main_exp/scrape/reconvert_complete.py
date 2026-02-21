#!/usr/bin/env python3
"""
Re-convert all manual-scrapes-complete HTML files to txt,
overwriting the thin/empty files from the first pass.
"""

import hashlib
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent.resolve()
MAIN_EXP_DIR = SCRIPT_DIR.parent
MOCK_INTERNET_DIR = MAIN_EXP_DIR / "mock_internet"
COMPLETE_DIR = SCRIPT_DIR / "manual-scrapes-complete"

HTML_TO_URL = {
    "How to Fix Memory Leaks in React Applications.html":
        ("https://www.freecodecamp.org/news/fix-memory-leaks-in-react-apps/",
         "react-native-memory-leak"),
    "Troubleshooting _localhost won't connect_ _ InMotion Hosting.html":
        ("https://www.inmotionhosting.com/support/website/error-numbers/localhost-refused-to-connect-error/",
         "docker-localhost-connection-refused"),
    "Git detached head_ What is it & How to fix it.html":
        ("https://kodekloud.com/blog/git-detached-head/",
         "git-merge-conflict-detached-head"),
    "How to Prevent Infinite Loops When Using useEffect() in ReactJS.html":
        ("https://www.freecodecamp.org/news/prevent-infinite-loops-when-using-useeffect-in-reactjs/",
         "react-useeffect-infinite-loop"),
    "How to Fix Cross-Origin Errors \u2014 CORS Error Explained.html":
        ("https://www.freecodecamp.org/news/how-to-fix-cross-origin-errors/",
         "cors-policy-blocked-by-access-control-allow-origin"),
    "How do I understand the out of memory errors in Node.js_ _ r_node.html":
        ("https://www.reddit.com/r/node/comments/1j16j8b/how_do_i_understand_the_out_of_memory_errors_in/",
         "nodejs-heap-out-of-memory"),
    "[Updated] How to Fix \u201cJavascript heap out of memory\u201d Error.html":
        ("https://www.betterbugs.io/blog/javascript-heap-out-of-memory-error-fix",
         "nodejs-heap-out-of-memory"),
    "Flutter pub get issues. _ r_flutterhelp.html":
        ("https://www.reddit.com/r/flutterhelp/comments/1al48sh/flutter_pub_get_issues/",
         "flutter-pub-get-failed"),
    "Trouble with installing cocoapods _ Apple Developer Forums.html":
        ("https://developer.apple.com/forums/thread/668456",
         "ios-cocoapods-pod-install-error"),
    "Why am I getting a CSRF Token missing when in fact it's there_ - Using Django _ Mystery Errors - Django Forum.html":
        ("https://forum.djangoproject.com/t/why-am-i-getting-a-csrf-token-missing-when-in-fact-its-there/24911",
         "django-csrf-token-missing-or-incorrect"),
    "Cross Site Request Forgery protection _ Django documentation _ Django.html":
        ("https://docs.djangoproject.com/en/6.0/ref/csrf/",
         "django-csrf-token-missing-or-incorrect"),
    "CSRF verification fails in unexpected situations - Using Django _ Mystery Errors - Django Forum.html":
        ("https://forum.djangoproject.com/t/csrf-verification-fails-in-unexpected-situations/26509",
         "django-csrf-token-missing-or-incorrect"),
    "Docker_ Despite modifying server.port value, application is starting in 8080 only. Need to know why _ r_SpringBoot.html":
        ("https://www.reddit.com/r/SpringBoot/comments/17jso57/docker_despite_modifying_serverport_value/",
         "spring-boot-port-8080-in-use"),
    "Panic_ assignment to entry in nil map - Getting Help - Go Forum.html":
        ("https://forum.golangbridge.org/t/panic-assignment-to-entry-in-nil-map/3332",
         "go-panic-assignment-to-entry-in-nil-map"),
    "Panic_ assignment to entry in nil map - Docker Hub - Docker Community Forums.html":
        ("https://forums.docker.com/t/panic-assignment-to-entry-in-nil-map/136806",
         "go-panic-assignment-to-entry-in-nil-map"),
    "Map is apparently nil even though I already assigned to it - Getting Help _ Code Review - Go Forum.html":
        ("https://forum.golangbridge.org/t/map-is-apparently-nil-even-though-i-already-assigned-to-it/28393",
         "go-panic-assignment-to-entry-in-nil-map"),
    "References and Borrowing - The Rust Programming Language.html":
        ("https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html",
         "rust-borrow-checker-error-cannot-borrow-as-mutable"),
    "Command _npm run build_ exited with 1 - Help - Vercel Community.html":
        ("https://community.vercel.com/t/command-npm-run-build-exited-with-1/5407",
         "vercel-deployment-failed-build-command-exited-with-1"),
}


def make_filename(url: str) -> str:
    domain = url.split("//")[-1].split("/")[0].replace("www.", "")
    url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{domain}_{url_hash}.txt"


def clean_html(filepath: Path) -> str:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding="latin-1") as f:
            content = f.read()

    soup = BeautifulSoup(content, "html.parser")

    for element in soup(["script", "style", "noscript", "iframe", "svg"]):
        element.extract()

    for element in soup.find_all(
        attrs={"class": re.compile(r"(cookie[-_]?consent|cookie[-_]?banner|popup[-_]overlay|modal[-_]overlay)", re.I)}
    ):
        if element.name in ("div", "section", "aside", "span"):
            element.extract()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    cleaned = "\n".join(chunk for chunk in lines if chunk)
    return cleaned


def main():
    html_files = list(COMPLETE_DIR.glob("*.html")) + list(COMPLETE_DIR.glob("*.htm"))
    print(f"Found {len(html_files)} complete HTML files\n")

    # Build a lookup by normalized name to handle minor filename differences
    file_lookup = {}
    for f in html_files:
        file_lookup[f.name] = f

    matched = 0
    unmatched = []
    improved = 0
    already_good = 0

    for html_name, (url, slug) in sorted(HTML_TO_URL.items()):
        html_path = file_lookup.get(html_name)
        if not html_path:
            unmatched.append(html_name)
            continue

        matched += 1
        txt_filename = make_filename(url)
        txt_path = MOCK_INTERNET_DIR / slug / "clean" / txt_filename

        old_content_len = 0
        if txt_path.exists():
            with open(txt_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                old_content = "".join(lines[2:])
                old_content_len = len(old_content)

        new_content = clean_html(html_path)

        if len(new_content) <= old_content_len:
            print(f"  SKIP (existing is better): {txt_filename}")
            print(f"         old={old_content_len} chars, new={len(new_content)} chars")
            already_good += 1
            continue

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"SOURCE_URL: {url}\n")
            f.write("-" * 50 + "\n")
            f.write(new_content)

        improvement = f"{old_content_len} -> {len(new_content)}"
        print(f"  UPDATED: {slug}/clean/{txt_filename}")
        print(f"           {improvement} chars")
        improved += 1

    if unmatched:
        # Try fuzzy match for files not in the map
        print(f"\n  Unmatched HTML files in map (checking filesystem):")
        for name in unmatched:
            print(f"    - {repr(name)}")

    # Also check if there are HTML files not in the map at all
    mapped_names = set(HTML_TO_URL.keys())
    extra_files = [f.name for f in html_files if f.name not in mapped_names]
    if extra_files:
        print(f"\n  HTML files in directory not in map:")
        for name in extra_files:
            print(f"    - {repr(name)}")

    print(f"\n=== SUMMARY ===")
    print(f"  Matched:      {matched}")
    print(f"  Improved:     {improved}")
    print(f"  Already good: {already_good}")
    print(f"  Unmatched:    {len(unmatched)}")


if __name__ == "__main__":
    main()
