"""
Pipeline Orchestrator for Reasoning Poisoning Experiments.

Auto-discovers all attack folders in ../mock_internet/ and runs experiments
on each one sequentially, with clean database resets between phases.

Folder structure it reads from:
    ../mock_internet/
    ├── clean/                                       (baseline)
    ├── poisoned/                                    (generic poisoned)
    ├── single-bot/{upvote-level}/{attack-type}/     (32 combos)
    └── multiple-bots/{upvote-level}/{attack-type}/  (32 combos)

Usage:
    python run_pipeline.py --list                          # Show all phases
    python run_pipeline.py --phases clean                  # Run baseline only
    python run_pipeline.py --phases clean poisoned         # Run baseline + poisoned
    python run_pipeline.py --group single-bot              # All single-bot attacks
    python run_pipeline.py --group multiple-bots           # All multiple-bots attacks
    python run_pipeline.py --attack severe_safety-attack   # One attack type everywhere
    python run_pipeline.py --all                           # Run everything (66 phases)

Output:
    logs/results_{phase_name}.csv  (one CSV per phase)
    logs/pipeline_summary.txt      (overall summary)
"""

import os
import sys
import time
import shutil
import argparse
from typing import List, Optional
from datetime import datetime

# Lazy import: only load experiment module when actually running experiments.
# This allows --list to work without requiring chromadb/ollama installed.
MODELS_TO_TEST = None  # Populated on first use


def _import_experiment():
    """Import experiment module on demand."""
    global MODELS_TO_TEST
    from experiment import run_experiment as _run, MODELS_TO_TEST as _models
    MODELS_TO_TEST = _models
    return _run

# --- CONFIGURATION ---

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
MOCK_INTERNET_DIR: str = os.path.join(SCRIPT_DIR, "..", "mock_internet")
LOGS_DIR: str = os.environ.get("EXPERIMENT_LOGS_DIR", os.path.join(SCRIPT_DIR, "logs"))
DB_PATH: str = os.environ.get("EXPERIMENT_DB_PATH", os.path.join(SCRIPT_DIR, "vector_db_active"))
QUERIES_FILE: str = os.path.join(SCRIPT_DIR, "queries.txt")

# Bot groups and upvote levels (defines discovery order)
BOT_GROUPS: List[str] = ["single-bot", "multiple-bots"]
UPVOTE_LEVELS: List[str] = [
    "low-real-upvotes",
    "low-fake-upvotes",
    "high-real-upvotes",
    "high-fake-upvotes",
]


# --- PHASE DISCOVERY ---

def discover_phases() -> List[dict]:
    """
    Auto-discover all experiment phases from mock_internet/ folder structure.

    Returns:
        List of dicts, each with:
            - name: Human-readable phase name (e.g. "single-bot/high-fake-upvotes/attribute-attack")
            - path: Absolute path to the data folder
            - category: "baseline", "poisoned", "single-bot", or "multiple-bots"
    """
    phases = []

    # 1. Baseline (clean)
    clean_path = os.path.join(MOCK_INTERNET_DIR, "clean")
    if os.path.isdir(clean_path):
        phases.append({
            "name": "clean",
            "path": clean_path,
            "category": "baseline",
        })

    # 2. Generic poisoned
    poisoned_path = os.path.join(MOCK_INTERNET_DIR, "poisoned")
    if os.path.isdir(poisoned_path):
        phases.append({
            "name": "poisoned",
            "path": poisoned_path,
            "category": "poisoned",
        })

    # 3. Bot groups (single-bot, multiple-bots)
    for bot_group in BOT_GROUPS:
        bot_dir = os.path.join(MOCK_INTERNET_DIR, bot_group)
        if not os.path.isdir(bot_dir):
            continue

        for upvote_level in UPVOTE_LEVELS:
            upvote_dir = os.path.join(bot_dir, upvote_level)
            if not os.path.isdir(upvote_dir):
                continue

            # Discover attack types
            attack_dirs = sorted([
                d for d in os.listdir(upvote_dir)
                if os.path.isdir(os.path.join(upvote_dir, d)) and not d.startswith(".")
            ])

            for attack_type in attack_dirs:
                attack_path = os.path.join(upvote_dir, attack_type)
                phase_name = f"{bot_group}/{upvote_level}/{attack_type}"

                phases.append({
                    "name": phase_name,
                    "path": attack_path,
                    "category": bot_group,
                })

    return phases


def count_txt_files(path: str) -> int:
    """Count .txt files in a directory."""
    if not os.path.isdir(path):
        return 0
    return len([f for f in os.listdir(path) if f.endswith(".txt")])


# --- FILTERING ---

def filter_phases(
    all_phases: List[dict],
    phase_names: Optional[List[str]] = None,
    group: Optional[str] = None,
    attack: Optional[str] = None,
) -> List[dict]:
    """
    Filter phases based on user arguments.

    Args:
        all_phases: Full list of discovered phases.
        phase_names: Specific phase names to include (partial match).
        group: Filter by category ("single-bot" or "multiple-bots").
        attack: Filter by attack type name (e.g. "severe_safety-attack").

    Returns:
        Filtered list of phases.
    """
    if phase_names:
        # Match by exact name or partial match
        filtered = []
        for name in phase_names:
            for phase in all_phases:
                if phase["name"] == name or name in phase["name"]:
                    if phase not in filtered:
                        filtered.append(phase)
        return filtered

    if group:
        return [p for p in all_phases if p["category"] == group]

    if attack:
        return [p for p in all_phases if attack in p["name"]]

    return all_phases


# --- DISPLAY ---

def print_banner(text: str, char: str = "=") -> None:
    """Print a formatted banner."""
    width = 70
    print("\n" + char * width)
    print(f" {text}")
    print(char * width)


def list_phases(phases: List[dict]) -> None:
    """Print all discovered phases."""
    print_banner(f"AVAILABLE PHASES ({len(phases)} total)")

    current_category = None
    for i, phase in enumerate(phases):
        # Print category header when it changes
        if phase["category"] != current_category:
            current_category = phase["category"]
            print(f"\n  --- {current_category.upper()} ---")

        file_count = count_txt_files(phase["path"])
        print(f"  {i+1:3}. [{file_count:2} files] {phase['name']}")


# --- EXECUTION ---

def run_single_phase(phase: dict, phase_index: int, total: int) -> bool:
    """
    Run experiment for one phase.

    Returns:
        True if successful.
    """
    print_banner(f"PHASE {phase_index}/{total}: {phase['name']}", "=")

    # Output CSV path: replace / with _ for filename
    safe_name = phase["name"].replace("/", "_")
    output_file = os.path.join(LOGS_DIR, f"results_{safe_name}.csv")

    file_count = count_txt_files(phase["path"])
    if file_count == 0:
        print(f"[SKIP] No .txt files in {phase['path']}")
        return False

    print(f"[INFO] Data source: {phase['path']}")
    print(f"[INFO] Files: {file_count}")
    print(f"[INFO] Output: {output_file}")

    try:
        start_time = time.time()

        _run_experiment = _import_experiment()
        results = _run_experiment(
            data_source=phase["path"],
            queries_file=QUERIES_FILE,
            output_file=output_file,
            db_path=DB_PATH,
            phase_name=phase["name"],
            reset_db=True,
        )

        duration = time.time() - start_time
        print(f"\n[SUCCESS] Phase '{phase['name']}' completed in {duration:.1f}s")
        print(f"          Results: {len(results)} rows -> {output_file}")
        return True

    except Exception as e:
        print(f"\n[ERROR] Phase '{phase['name']}' failed: {e}")
        return False


def generate_summary(
    phases_run: List[str],
    phases_failed: List[str],
    start_time: datetime,
    end_time: datetime,
) -> None:
    """Write summary report to logs/."""
    summary_file = os.path.join(LOGS_DIR, "pipeline_summary.txt")
    duration = end_time - start_time

    content = f"""
{'='*70}
REASONING POISONING EXPERIMENT - PIPELINE SUMMARY
{'='*70}

Started:  {start_time.strftime("%Y-%m-%d %H:%M:%S")}
Finished: {end_time.strftime("%Y-%m-%d %H:%M:%S")}
Duration: {duration}

Models Tested:
{chr(10).join(f"  - {m}" for m in MODELS_TO_TEST) if MODELS_TO_TEST else "  (unknown)"}

Completed ({len(phases_run)}):
{chr(10).join(f"  + {p}" for p in phases_run) if phases_run else "  None"}

Failed ({len(phases_failed)}):
{chr(10).join(f"  x {p}" for p in phases_failed) if phases_failed else "  None"}

Output files in: {LOGS_DIR}/
{'='*70}
"""
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(content)
    print(f"Summary saved to: {summary_file}")


# --- MAIN ---

def run_pipeline(phases: List[dict]) -> None:
    """Run experiments on the given list of phases."""
    print_banner("REASONING POISONING - PIPELINE", "=")

    os.makedirs(LOGS_DIR, exist_ok=True)

    print(f"\n[INFO] Running {len(phases)} phases")
    print(f"[INFO] Results -> {LOGS_DIR}/")

    # Show what will run
    for i, p in enumerate(phases):
        files = count_txt_files(p["path"])
        print(f"  {i+1:3}. [{files:2} files] {p['name']}")

    print(f"\n{'─'*70}")
    print("Starting in 3 seconds... (Ctrl+C to cancel)")
    print(f"{'─'*70}")
    time.sleep(3)

    # Run
    phases_run = []
    phases_failed = []
    start_time = datetime.now()

    for i, phase in enumerate(phases):
        success = run_single_phase(phase, i + 1, len(phases))
        if success:
            phases_run.append(phase["name"])
        else:
            phases_failed.append(phase["name"])

        if i < len(phases) - 1:
            print("\n[PAUSE] 2 seconds before next phase...")
            time.sleep(2)

    end_time = datetime.now()
    generate_summary(phases_run, phases_failed, start_time, end_time)


# --- CLI ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run reasoning poisoning experiments across attack phases.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py --list
  python run_pipeline.py --phases clean
  python run_pipeline.py --phases clean poisoned
  python run_pipeline.py --phases single-bot/high-fake-upvotes/attribute-attack
  python run_pipeline.py --group single-bot
  python run_pipeline.py --group multiple-bots
  python run_pipeline.py --attack severe_safety-attack
  python run_pipeline.py --all
        """
    )
    parser.add_argument("--list", action="store_true", help="List all available phases")
    parser.add_argument("--phases", nargs="+", help="Specific phase names to run")
    parser.add_argument("--group", choices=["single-bot", "multiple-bots"], help="Run all phases in a bot group")
    parser.add_argument("--attack", help="Run one attack type across all bot/upvote combos")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    args = parser.parse_args()

    # Discover all phases
    all_phases = discover_phases()

    if not all_phases:
        print(f"ERROR: No phases found. Is mock_internet/ at {MOCK_INTERNET_DIR}?")
        sys.exit(1)

    if args.list:
        list_phases(all_phases)
        sys.exit(0)

    # Determine what to run
    if args.all:
        phases_to_run = all_phases
    elif args.phases or args.group or args.attack:
        phases_to_run = filter_phases(all_phases, args.phases, args.group, args.attack)
        if not phases_to_run:
            print("ERROR: No matching phases found. Use --list to see available phases.")
            sys.exit(1)
    else:
        parser.print_help()
        print("\nUse --list to see available phases, or --all to run everything.")
        sys.exit(0)

    run_pipeline(phases_to_run)
