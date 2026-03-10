"""
Ablation Study Runner for Taxi-Driver Domain.

Runs identically to the main experiment pipeline:
  - Model: deepseek-r1:8b via Ollama
  - Context: attack_plus_random_clean mode (all 236207 files + 1 random clean)
  - Prompt: same build_prompt() as experiment.py
  - All 50 queries from the shared CSV

Two experiments:
  1. Safety Ablation — isolates the effect of defamation type and promotion
     Variants: baseline, promotion_only, quality_defamation, safety_no_promotion
  2. Recency Ablation — isolates the effect of how recent the fake review appears
     Variants: baseline_with_date, days_ago, weeks_ago, months_ago, years_ago
     All recency variants inject a date system directive into the prompt.

Output: logs/results_ablation_{variant}.csv per variant (same format as main experiment).

Usage:
    EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean python run_ablation_experiments.py
    EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean python run_ablation_experiments.py --max-queries 5
    EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean python run_ablation_experiments.py --experiment safety
    EXPERIMENT_CONTEXT_MODE=attack_plus_random_clean python run_ablation_experiments.py --experiment recency
"""

from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from experiment import (
    RANDOM_SEED,
    NUM_CTX,
    MODEL_KEEP_ALIVE,
    build_prompt as experiment_build_prompt,
    retrieve_attack_plus_random_clean_context,
    warm_up_model,
    unload_model,
    run_model,
    parse_response,
    get_model_type,
    ExperimentResult,
    save_results_csv,
)

MODEL_NAME = "deepseek-r1:8b"
QUERIES_CSV = SCRIPT_DIR / "source-gather" / "20_domains_50_queries.csv"
ATTACK_DIR = SCRIPT_DIR / "mock_internet" / "taxi-driver" / "multiple-bots" / "no-upvotes" / "severe_safety-attack"
LOGS_DIR = SCRIPT_DIR / "logs"

ABLATION_ROOT = SCRIPT_DIR / "mock_internet" / "taxi-driver" / "ablations"

SAFETY_VARIANTS: Dict[str, Path] = {
    "safety_baseline":     ATTACK_DIR,
    "promotion_only":      ABLATION_ROOT / "safety" / "promotion_only",
    "quality_defamation":  ABLATION_ROOT / "safety" / "quality_defamation",
    "safety_no_promotion": ABLATION_ROOT / "safety" / "safety_no_promotion",
}

RECENCY_VARIANTS: Dict[str, Path] = {
    "baseline_with_date": ABLATION_ROOT / "recency" / "baseline_with_date",
    "days_ago":           ABLATION_ROOT / "recency" / "days_ago",
    "weeks_ago":          ABLATION_ROOT / "recency" / "weeks_ago",
    "months_ago":         ABLATION_ROOT / "recency" / "months_ago",
    "years_ago":          ABLATION_ROOT / "recency" / "years_ago",
}

DATE_DIRECTIVE = "[SYSTEM: Today's date is March 4, 2026. Use this date as your reference point for all temporal reasoning.]\n\n"


def load_queries(max_queries: int = 50) -> List[Tuple[int, str]]:
    queries: List[Tuple[int, str]] = []
    with open(QUERIES_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["Domain"] == "Taxi Driver":
                queries.append((int(row["Query ID"]), row["Query"]))
                if len(queries) >= max_queries:
                    break
    return queries


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ablation study for taxi-driver domain.")
    parser.add_argument("--max-queries", type=int, default=50)
    parser.add_argument("--experiment", choices=["safety", "recency", "all"], default="all",
                        help="Which experiment to run (default: all)")
    args = parser.parse_args()

    queries = load_queries(args.max_queries)
    n_queries = len(queries)
    model_type = get_model_type(MODEL_NAME)

    variant_map: Dict[str, Path] = {}
    variant_names: List[str] = []

    if args.experiment in ("safety", "all"):
        variant_names.extend(SAFETY_VARIANTS.keys())
        variant_map.update(SAFETY_VARIANTS)

    if args.experiment in ("recency", "all"):
        for v in RECENCY_VARIANTS:
            if v not in variant_names:
                variant_names.append(v)
        variant_map.update(RECENCY_VARIANTS)

    n_variants = len(variant_names)

    print("=" * 72)
    print("ABLATION STUDY — Taxi Driver Domain")
    print("=" * 72)
    print(f"Model:      {MODEL_NAME} (via Ollama)")
    print(f"Experiment: {args.experiment}")
    print(f"Queries:    {n_queries}")
    print(f"Variants:   {n_variants} ({', '.join(variant_names)})")
    print(f"Total:      {n_queries * n_variants} runs")
    print("=" * 72)

    warm_up_model(MODEL_NAME)
    os.makedirs(LOGS_DIR, exist_ok=True)

    total_runs = n_queries * n_variants
    run_idx = 0

    for variant in variant_names:
        phase_name = f"taxi-driver/ablation/{variant}"
        results: List[ExperimentResult] = []

        print(f"\n{'─'*72}")
        print(f"VARIANT: {variant}")
        print(f"{'─'*72}")

        for q_idx, (qid, qtext) in enumerate(queries):
            run_idx += 1

            data_dir = variant_map[variant]
            context_str, sources = retrieve_attack_plus_random_clean_context(
                data_source=str(data_dir),
                query_id=qid,
                query_text=qtext,
                phase_name=phase_name,
            )
            sources_str = ", ".join(sources)

            prompt = experiment_build_prompt(qtext, context_str)
            if variant in RECENCY_VARIANTS:
                prompt = DATE_DIRECTIVE + prompt

            print(f"  [{run_idx:3d}/{total_runs}] Q{qid}: {qtext[:50]}...", end="", flush=True)
            response_text, duration = run_model(MODEL_NAME, prompt)
            chain_of_thought, final_answer = parse_response(response_text)

            results.append(ExperimentResult(
                phase=phase_name,
                query_id=qid,
                query=qtext,
                model=MODEL_NAME,
                model_type=model_type,
                chain_of_thought=chain_of_thought,
                final_answer=final_answer,
                full_response=response_text,
                response_time_sec=round(duration, 2),
                sources_used=sources_str,
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            ))

        output_file = str(LOGS_DIR / f"results_ablation_{variant}.csv")
        save_results_csv(results, output_file)

    unload_model(MODEL_NAME)

    print("\n" + "=" * 72)
    print("ABLATION COMPLETE")
    print(f"Results saved to {LOGS_DIR}/results_ablation_*.csv")
    print("=" * 72)


if __name__ == "__main__":
    main()
