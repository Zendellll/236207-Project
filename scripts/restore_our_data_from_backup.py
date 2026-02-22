#!/usr/bin/env python3
"""
Restore our tourism data from a backup (e.g. after a bad merge).

Usage:
    python3 scripts/restore_our_data_from_backup.py              # use latest backup
    python3 scripts/restore_our_data_from_backup.py 20250214_123456   # use this timestamp
"""

import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
BACKUP_PARENT = os.path.join(ROOT, "_backup_our_data")

QUERIES_DEST = os.path.join(ROOT, "experiment_pipeline", "queries", "domains")
MOCK_INTERNET_DEST = os.path.join(ROOT, "mock_internet")


def main():
    if not os.path.isdir(BACKUP_PARENT):
        print(f"No backup folder found: {BACKUP_PARENT}")
        return 1

    # Pick backup: latest or given timestamp
    if len(sys.argv) > 1:
        timestamp = sys.argv[1]
        backup_dir = os.path.join(BACKUP_PARENT, timestamp)
        if not os.path.isdir(backup_dir):
            print(f"Backup not found: {backup_dir}")
            return 1
    else:
        timestamps = sorted([d for d in os.listdir(BACKUP_PARENT) if os.path.isdir(os.path.join(BACKUP_PARENT, d))])
        if not timestamps:
            print(f"No backups in {BACKUP_PARENT}")
            return 1
        backup_dir = os.path.join(BACKUP_PARENT, timestamps[-1])
        print(f"Using latest backup: {timestamps[-1]}")

    # Restore queries
    queries_src = os.path.join(backup_dir, "queries", "domains")
    if os.path.isdir(queries_src):
        os.makedirs(QUERIES_DEST, exist_ok=True)
        for name in os.listdir(queries_src):
            if name.endswith(".txt"):
                shutil.copy2(os.path.join(queries_src, name), os.path.join(QUERIES_DEST, name))
        print(f"[OK] Restored queries -> {QUERIES_DEST}")
    else:
        print(f"[SKIP] No queries in backup: {queries_src}")

    # Restore mock_internet domains
    mock_src = os.path.join(backup_dir, "mock_internet")
    if os.path.isdir(mock_src):
        for domain in os.listdir(mock_src):
            src = os.path.join(mock_src, domain)
            if os.path.isdir(src):
                dest = os.path.join(MOCK_INTERNET_DEST, domain)
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                print(f"[OK] Restored mock_internet/{domain}")
    else:
        print(f"[SKIP] No mock_internet in backup: {mock_src}")

    print("Restore complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
