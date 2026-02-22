#!/usr/bin/env python3
"""
Fix broken clean data files by converting manually-scraped HTML replacements.

For each <domain>/clean-to-fix/<name>.html, converts to text and overwrites
the corresponding <domain>/clean/<name>.txt.

Conversion follows the same approach as scrape/reconvert_complete.py:
- Removes script, style, noscript, iframe, svg
- Removes cookie consent/banner overlays
- Keeps all visible text (including nav, header, footer) to match
  the format of existing good clean files
- Preserves the SOURCE_URL header from the original .txt file

After fixing clean/, propagates the fixed file to every attack variant
directory and re-injects any attacks that were previously applied.
"""

import re
import shutil
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent.resolve()
MI = SCRIPT_DIR / "mock_internet"

BOT_CONFIGS = ["single-bot", "multiple-bots"]
UPVOTE_LEVELS = ["no-upvotes", "low-fake-upvotes", "high-fake-upvotes"]
ATTACK_TYPES = ["attribute-attack", "fake_authority-attack", "severe_safety-attack"]


def clean_html(filepath: Path) -> str:
    """Convert an HTML file to clean text, matching existing good file format."""
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
        attrs={
            "class": re.compile(
                r"(cookie[-_]?consent|cookie[-_]?banner|popup[-_]overlay|modal[-_]overlay)",
                re.I,
            )
        }
    ):
        if element.name in ("div", "section", "aside", "span"):
            element.extract()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    cleaned = "\n".join(chunk for chunk in lines if chunk)
    return cleaned


def get_source_url(txt_path: Path) -> str:
    """Extract SOURCE_URL from an existing .txt file."""
    if not txt_path.exists():
        return ""
    with open(txt_path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
    if first_line.startswith("SOURCE_URL:"):
        return first_line.replace("SOURCE_URL:", "").strip()
    return ""


def convert_and_replace(dry_run=False):
    """Step 1: Convert HTML files in clean-to-fix and replace broken clean files."""
    results = []

    for domain_dir in sorted(MI.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name == ".DS_Store":
            continue

        fix_dir = domain_dir / "clean-to-fix"
        clean_dir = domain_dir / "clean"
        if not fix_dir.exists():
            continue

        html_files = sorted(fix_dir.glob("*.html"))
        if not html_files:
            continue

        for html_file in html_files:
            base_name = html_file.stem
            txt_path = clean_dir / f"{base_name}.txt"

            source_url = get_source_url(txt_path)
            if not source_url:
                # Try to extract URL from HTML canonical/og:url
                try:
                    with open(html_file, "r", encoding="utf-8", errors="replace") as f:
                        soup = BeautifulSoup(f.read(), "html.parser")
                    canonical = soup.find("link", rel="canonical")
                    if canonical and canonical.get("href"):
                        source_url = canonical["href"]
                    else:
                        og_url = soup.find("meta", property="og:url")
                        if og_url and og_url.get("content"):
                            source_url = og_url["content"]
                except Exception:
                    pass
                if not source_url:
                    source_url = f"UNKNOWN (from {html_file.name})"

            old_size = txt_path.stat().st_size if txt_path.exists() else 0
            new_content = clean_html(html_file)

            full_output = f"SOURCE_URL: {source_url}\n" + "-" * 50 + "\n" + new_content
            new_size = len(full_output.encode("utf-8"))

            if new_size <= old_size:
                print(f"  WARNING: New version is not larger ({old_size} -> {new_size}): {domain_dir.name}/{base_name}")
                print(f"           Replacing anyway (old file was broken)")

            if dry_run:
                print(f"  DRY: {domain_dir.name}/clean/{base_name}.txt ({old_size} -> {new_size} bytes)")
            else:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(full_output)
                print(f"  FIXED: {domain_dir.name}/clean/{base_name}.txt ({old_size} -> {new_size} bytes)")

            results.append({
                "domain": domain_dir.name,
                "file": f"{base_name}.txt",
                "old_size": old_size,
                "new_size": new_size,
                "url": source_url,
            })

    return results


def propagate_to_variants(results, dry_run=False):
    """Step 2: Copy fixed clean files to all attack variant directories."""
    propagated = 0
    errors = []

    for r in results:
        domain = r["domain"]
        filename = r["file"]
        clean_path = MI / domain / "clean" / filename

        if not clean_path.exists():
            errors.append(f"Clean file missing after fix: {clean_path}")
            continue

        for bot in BOT_CONFIGS:
            for level in UPVOTE_LEVELS:
                for attack in ATTACK_TYPES:
                    variant_dir = MI / domain / bot / level / attack
                    variant_path = variant_dir / filename
                    if not variant_dir.exists():
                        continue
                    if not variant_path.exists():
                        continue

                    if dry_run:
                        print(f"  DRY PROPAGATE: {domain}/{bot}/{level}/{attack}/{filename}")
                    else:
                        shutil.copy2(clean_path, variant_path)
                        propagated += 1

    if not dry_run:
        print(f"\n  Propagated to {propagated} variant files")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")

    return propagated


def main():
    dry_run = "--dry-run" in sys.argv
    step = "all"
    if "--convert-only" in sys.argv:
        step = "convert"
    elif "--propagate-only" in sys.argv:
        step = "propagate"

    if dry_run:
        print("*** DRY RUN ***\n")

    if step in ("all", "convert"):
        print("=== STEP 1: Convert HTML and replace broken clean files ===")
        results = convert_and_replace(dry_run)
        print(f"\n  Total files processed: {len(results)}")
    else:
        results = []

    if step in ("all", "propagate"):
        print("\n=== STEP 2: Propagate fixed files to variant directories ===")
        print("  (This overwrites variant copies with clean versions;")
        print("   attacks must be re-injected after this step)")
        if not results:
            # Rebuild results from clean-to-fix dirs
            for domain_dir in sorted(MI.iterdir()):
                if not domain_dir.is_dir():
                    continue
                fix_dir = domain_dir / "clean-to-fix"
                if not fix_dir.exists():
                    continue
                for html_file in sorted(fix_dir.glob("*.html")):
                    results.append({
                        "domain": domain_dir.name,
                        "file": f"{html_file.stem}.txt",
                    })
        propagate_to_variants(results, dry_run)

    if step == "all" and not dry_run:
        print("\n=== IMPORTANT: Re-inject attacks into fixed files ===")
        print("  The variant files are now clean copies.")
        print("  Run inject_attribute_attack.py and inject_fake_authority_attack.py")
        print("  to re-apply attacks to the relevant files.")


if __name__ == "__main__":
    main()
