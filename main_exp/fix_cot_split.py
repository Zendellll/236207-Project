"""
Fix chain_of_thought / final_answer split in result CSVs.

DeepSeek-R1 via Ollama doesn't always use <think> tags, so experiment.py
puts everything in final_answer and leaves chain_of_thought empty.

This script re-parses full_response using the structural headers the model
actually produces (e.g. **Final Answer:**, ## Recommendation, etc.) and
overwrites chain_of_thought and final_answer in the CSV.

Usage:
    python fix_cot_split.py logs/results_taxi-driver_clean.csv
    python fix_cot_split.py logs/results_ablation_safety_baseline.csv
    python fix_cot_split.py logs/*.csv          # all at once
    python fix_cot_split.py --dry-run logs/results_taxi-driver_clean.csv
"""

import csv
import re
import sys
import os
from typing import Tuple

ANSWER_HEADERS = [
    r"\n\*\*\s*(?:FINAL\s+)?ANSWER\s*[:*]*\s*\*\*",
    r"\n\*\*\s*(?:FINAL\s+)?ANSWER\s*:\s*\*\*",
    r"\n##\s+(?:Final\s+)?Answer\b",
    r"\n\*\*\s*Conclusion\s*[:*]*\s*\*\*",
    r"\n##\s+Conclusion\b",
    r"\n\*\*\s*Recommendation\s*[:*]*\s*\*\*",
    r"\n##\s+Recommendation\b",
    r"\n\*\*\s*Summary\s*[:*]*\s*\*\*",
    r"\n##\s+Summary\b",
    r"\n\*\*\s*Verdict\s*[:*]*\s*\*\*",
    r"\n##\s+Verdict\b",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in ANSWER_HEADERS]


def split_cot_answer(full_response: str) -> Tuple[str, str]:
    """Split full_response into (chain_of_thought, final_answer).

    Finds the LAST matching header (the model sometimes has intermediate
    headers before the real final answer at the bottom).
    """
    text = full_response.strip()
    if not text:
        return "", ""

    best_pos = -1
    best_match = None

    for pattern in COMPILED_PATTERNS:
        for m in pattern.finditer(text):
            if m.start() > best_pos and m.start() > len(text) * 0.15:
                best_pos = m.start()
                best_match = m

    if best_match is not None:
        cot = text[:best_match.start()].strip()
        answer = text[best_match.start():].strip()
        return cot, answer

    # Fallback: look for --- separator
    parts = text.rsplit("\n---\n", 1)
    if len(parts) == 2 and len(parts[1].strip()) > 50:
        return parts[0].strip(), parts[1].strip()

    return "", text


def process_csv(filepath: str, dry_run: bool = False) -> dict:
    """Process one CSV file. Returns stats dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if "full_response" not in fieldnames or "chain_of_thought" not in fieldnames:
        return {"file": filepath, "skipped": True, "reason": "missing columns"}

    split_count = 0
    nosplit_count = 0

    for row in rows:
        full = row.get("full_response", "")
        cot, answer = split_cot_answer(full)

        if cot:
            split_count += 1
        else:
            nosplit_count += 1

        row["chain_of_thought"] = cot
        row["final_answer"] = answer

    if not dry_run:
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return {
        "file": os.path.basename(filepath),
        "total": len(rows),
        "split": split_count,
        "no_split": nosplit_count,
        "dry_run": dry_run,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fix CoT/answer split in result CSVs")
    parser.add_argument("files", nargs="+", help="CSV files to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't write changes")
    args = parser.parse_args()

    print(f"{'DRY RUN — ' if args.dry_run else ''}Processing {len(args.files)} file(s)...\n")

    for filepath in args.files:
        if not os.path.isfile(filepath):
            print(f"  [SKIP] {filepath} — not found")
            continue

        stats = process_csv(filepath, dry_run=args.dry_run)

        if stats.get("skipped"):
            print(f"  [SKIP] {stats['file']} — {stats['reason']}")
        else:
            action = "would update" if args.dry_run else "updated"
            print(f"  [{action}] {stats['file']}: "
                  f"{stats['split']}/{stats['total']} split, "
                  f"{stats['no_split']} kept as-is")

    print("\nDone.")


if __name__ == "__main__":
    main()
