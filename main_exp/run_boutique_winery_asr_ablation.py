"""
Boutique Winery — poison-fraction (ASR) ablation for the Tripadvisor mega corpus.

Same experiment loop as the main pipeline (`experiment.run_experiment`):
  - Queries: Boutique Winery rows from `source-gather/20_domains_50_queries.csv`
  - Prompting / models / CSV schema: identical to `run_main_experiment.py`
  - Context: `EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean` (defaulted here if unset)

Unlike `mock_internet/` phases, each ASR variant is a **single** combined `.txt` page.
`attack_plus_random_clean` normally takes all `236207*.txt` plus one random clean file;
these megas have no `236207` prefix, so we stage **one symlink per variant** under
`mock_int_optimization/boutique-winery/ablation/_single_txt_context/<asrXX>/`
so the directory passed to `run_experiment` contains exactly one `.txt` and the
full page is always in context.

Outputs (separate CSV per variant, judge-compatible):
  logs/results_boutique-winery_asr_ablation_asrXX.csv

Usage:
  EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean python run_boutique_winery_asr_ablation.py
  python run_boutique_winery_asr_ablation.py --max-queries 5
  python run_boutique_winery_asr_ablation.py --list
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

os.environ.setdefault("EXPERIMENT_CONTEXT_MODE", "attack_plus_random_clean")

ABLATION_DIR = SCRIPT_DIR / "mock_int_optimization" / "boutique-winery" / "ablation"
CONTEXT_STAGING = ABLATION_DIR / "_single_txt_context"
MEGA_PATTERN = re.compile(r"boutique-winery_severe_safety_mega_asr(\d+)\.txt$")


def _import_run_experiment():
    from experiment import run_experiment

    return run_experiment


def _load_boutique_queries() -> List[Tuple[int, str]]:
    from run_main_experiment import load_domain_queries

    qmap = load_domain_queries()
    queries = qmap.get("boutique-winery")
    if not queries:
        raise SystemExit(
            "No 'Boutique Winery' queries in source-gather/20_domains_50_queries.csv"
        )
    return queries


def discover_mega_files() -> List[Path]:
    files = [p for p in ABLATION_DIR.iterdir() if p.is_file() and MEGA_PATTERN.match(p.name)]
    return sorted(files, key=lambda p: int(MEGA_PATTERN.match(p.name).group(1)), reverse=True)


def ensure_single_file_context_dir(mega: Path) -> Path:
    """
    Return a directory that contains exactly this mega as a .txt (symlink),
    so attack_plus_random_clean loads only that document.
    """
    m = MEGA_PATTERN.match(mega.name)
    label = f"asr{m.group(1)}" if m else mega.stem
    d = CONTEXT_STAGING / label
    d.mkdir(parents=True, exist_ok=True)
    link = d / mega.name
    rel_target = os.path.relpath(mega, d)

    if link.is_symlink() or link.exists():
        if link.is_symlink() and mega.resolve() == link.resolve():
            return d
        link.unlink()

    link.symlink_to(rel_target)
    return d


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Boutique Winery ASR ablation (single mega per phase, attack_plus_random_clean)."
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=None,
        metavar="N",
        help="Only first N queries (quick test).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered mega files and exit.",
    )
    args = parser.parse_args()

    megas = discover_mega_files()
    if args.list:
        print(f"ABLATION_DIR: {ABLATION_DIR}")
        for p in megas:
            print(f"  {p.name}")
        print(f"({len(megas)} file(s))")
        return

    if not megas:
        print(f"ERROR: No boutique-winery_severe_safety_mega_asr*.txt in:\n  {ABLATION_DIR}")
        sys.exit(1)

    mode = os.environ.get("EXPERIMENT_CONTEXT_MODE", "").strip().lower()
    if mode != "attack_plus_random_clean":
        print(
            f"WARN: EXPERIMENT_CONTEXT_MODE={mode!r} — expected 'attack_plus_random_clean'.\n"
            f"      This script setdefault only applies if the variable was unset before import.\n"
            f"      Export EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean and re-run.",
            file=sys.stderr,
        )

    queries = _load_boutique_queries()
    if args.max_queries is not None and args.max_queries > 0:
        queries = queries[: args.max_queries]

    logs_dir = Path(os.environ.get("EXPERIMENT_LOGS_DIR", str(SCRIPT_DIR / "logs")))
    logs_dir.mkdir(parents=True, exist_ok=True)
    db_path = os.environ.get("EXPERIMENT_DB_PATH", str(SCRIPT_DIR / "vector_db_active"))

    run_experiment = _import_run_experiment()
    started = datetime.now()
    ok: List[str] = []
    failed: List[str] = []

    print("=" * 72)
    print("BOUTIQUE WINERY — ASR ABLATION (single mega per phase)")
    print("=" * 72)
    print(f"Queries:     {len(queries)}")
    print(f"Variants:    {len(megas)}")
    print(f"Logs dir:    {logs_dir}")
    print(f"Staging:     {CONTEXT_STAGING}")
    print("=" * 72)

    for mega in megas:
        m = MEGA_PATTERN.match(mega.name)
        num = m.group(1) if m else "unknown"
        phase_name = f"boutique-winery/asr_ablation/asr{num}"
        safe = phase_name.replace("/", "_")
        out_csv = logs_dir / f"results_{safe}.csv"
        data_dir = ensure_single_file_context_dir(mega)

        print(f"\n--- Phase: {phase_name} ---")
        print(f"    Data: {data_dir} -> {mega.name}")

        try:
            run_experiment(
                data_source=str(data_dir),
                queries=queries,
                output_file=str(out_csv),
                db_path=db_path,
                phase_name=phase_name,
                reset_db=True,
            )
            ok.append(phase_name)
        except Exception as e:
            print(f"[ERROR] {phase_name}: {e}")
            failed.append(phase_name)
            import traceback

            traceback.print_exc()

        time.sleep(1)

    finished = datetime.now()
    summary_path = logs_dir / "boutique_winery_asr_ablation_summary.txt"
    body = (
        f"Boutique Winery ASR ablation summary\n"
        f"Started:  {started}\n"
        f"Finished: {finished}\n"
        f"OK ({len(ok)}): {ok}\n"
        f"Failed ({len(failed)}): {failed}\n"
    )
    summary_path.write_text(body, encoding="utf-8")
    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    main()
