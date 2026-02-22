#!/usr/bin/env python3
"""
Backup our tourism data before merging with origin/main.

Copies to _backup_our_data/<timestamp>/ so nothing is lost during merge.
Run this BEFORE any git merge with origin/main.

Usage:
    python3 scripts/backup_our_data.py
"""

import os
import shutil
from datetime import datetime

# Project root (parent of scripts/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)

# What we back up
QUERIES_SOURCE = os.path.join(ROOT, "experiment_pipeline", "queries", "domains")
TOURISM_DOMAINS = [
    "taxi-driver",
    "food-tour-guide",
    "surf-school",
    "scuba-diving-center",
    "boutique-winery",
    "cooking-class",
    "glamping",
    "historical-tour-guide",
    "jeep-tours",
    "vacation-photographer",
]
MOCK_INTERNET_SOURCE = os.path.join(ROOT, "mock_internet")
BACKUP_PARENT = os.path.join(ROOT, "_backup_our_data")


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(BACKUP_PARENT, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    # 1. Back up queries
    queries_dest = os.path.join(backup_dir, "queries", "domains")
    os.makedirs(queries_dest, exist_ok=True)
    if os.path.isdir(QUERIES_SOURCE):
        for name in os.listdir(QUERIES_SOURCE):
            if name.endswith(".txt"):
                src = os.path.join(QUERIES_SOURCE, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(queries_dest, name))
        print(f"[OK] Queries backed up -> {queries_dest}")
    else:
        print(f"[SKIP] Queries dir not found: {QUERIES_SOURCE}")

    # 2. Back up tourism mock_internet domains
    mock_dest = os.path.join(backup_dir, "mock_internet")
    os.makedirs(mock_dest, exist_ok=True)
    for domain in TOURISM_DOMAINS:
        src = os.path.join(MOCK_INTERNET_SOURCE, domain)
        if os.path.isdir(src):
            dest = os.path.join(mock_dest, domain)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            print(f"[OK] mock_internet/{domain} -> {dest}")
        else:
            print(f"[SKIP] Not found: {src}")

    print(f"\nBackup complete: {backup_dir}")
    print("Keep this folder until main_exp has the same data and the pipeline runs.")
    print("Add '_backup_our_data/' to .gitignore if you don't want it committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
