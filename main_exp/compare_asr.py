"""
Compare ASR between original judged results and optimized-comments judged results.

Filters both to: single-bot, no-upvotes, attribute attack, and only the 6 domains
in mock_int_optimization (boutique-winery, glamping, historical-tour-guide,
scuba-diving-center, surf-school, taxi-driver).

Usage:
    python compare_asr.py \
        --original logs/judged_results.csv \
        --optimized optimized_comments_attr_results/judged_results.csv \
        --outdir comparison_output

    # Or with custom paths:
    python compare_asr.py --original /path/to/original_judged.csv --optimized /path/to/optimized_judged.csv
"""

import os
import sys
import argparse

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas")

# The 6 domains in mock_int_optimization
EXAMINED_DOMAINS = {
    "boutique-winery",
    "glamping",
    "historical-tour-guide",
    "scuba-diving-center",
    "surf-school",
    "taxi-driver",
}


def filter_for_comparison(df: pd.DataFrame, attack: str = "attribute") -> pd.DataFrame:
    """Filter to single-bot, no-upvotes, specified attack, examined domains only."""
    out = df.copy()
    if "bot_group" in out.columns:
        out = out[out["bot_group"] == "single-bot"]
    if "upvote" in out.columns:
        out = out[out["upvote"] == "no-upvotes"]
    if "attack" in out.columns:
        out = out[out["attack"] == attack]
    if "domain" in out.columns:
        out = out[out["domain"].isin(EXAMINED_DOMAINS)]
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Compare ASR (original vs optimized) for single-bot, no-upvotes, attribute attack."
    )
    parser.add_argument(
        "--original",
        required=True,
        help="Path to original judged CSV (all tourism, all bot groups, all upvotes)",
    )
    parser.add_argument(
        "--optimized",
        required=True,
        help="Path to optimized judged CSV (mock_int_optimization results)",
    )
    parser.add_argument(
        "--outdir",
        default="comparison_output",
        help="Output directory for comparison table and chart",
    )
    parser.add_argument(
        "--attack",
        default="attribute",
        help="Attack type to compare (default: attribute)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.original):
        sys.exit(f"ERROR: Original file not found: {args.original}")
    if not os.path.isfile(args.optimized):
        sys.exit(f"ERROR: Optimized file not found: {args.optimized}")

    orig_df = pd.read_csv(args.original)
    opt_df = pd.read_csv(args.optimized)

    # Validate required columns
    for name, df in [("original", orig_df), ("optimized", opt_df)]:
        required = {"domain", "judge_score"}
        missing = required - set(df.columns)
        if missing:
            sys.exit(f"ERROR: {name} CSV missing columns: {missing}")

    # Filter both to single-bot, no-upvotes, specified attack, examined domains
    orig_filtered = filter_for_comparison(orig_df, attack=args.attack)
    opt_filtered = filter_for_comparison(opt_df, attack=args.attack)

    # Compute ASR per domain for each
    orig_asr = (
        orig_filtered.groupby("domain")["judge_score"]
        .agg(["mean", "count", "sum"])
        .rename(columns={"mean": "ASR", "count": "n", "sum": "successes"})
        .reset_index()
    )
    orig_asr["ASR%"] = (orig_asr["ASR"] * 100).round(1)
    orig_asr = orig_asr.rename(columns={"ASR%": "Original ASR%", "n": "Original n"})

    opt_asr = (
        opt_filtered.groupby("domain")["judge_score"]
        .agg(["mean", "count", "sum"])
        .rename(columns={"mean": "ASR", "count": "n", "sum": "successes"})
        .reset_index()
    )
    opt_asr["ASR%"] = (opt_asr["ASR"] * 100).round(1)
    opt_asr = opt_asr.rename(columns={"ASR%": "Optimized ASR%", "n": "Optimized n"})

    # Merge on domain (outer join so we see all domains from either source)
    comparison = orig_asr[["domain", "Original ASR%", "Original n"]].merge(
        opt_asr[["domain", "Optimized ASR%", "Optimized n"]],
        on="domain",
        how="outer",
    )

    # Ensure domain order matches EXAMINED_DOMAINS
    domain_order = sorted(EXAMINED_DOMAINS)
    present = comparison["domain"].tolist()
    order = [d for d in domain_order if d in present] + [d for d in present if d not in domain_order]
    comparison["domain"] = pd.Categorical(comparison["domain"], categories=order, ordered=True)
    comparison = comparison.sort_values("domain").reset_index(drop=True)

    # Add delta column
    comparison["Delta (pp)"] = comparison["Optimized ASR%"] - comparison["Original ASR%"]
    comparison["Delta (pp)"] = comparison["Delta (pp)"].round(1)

    # Print and save
    os.makedirs(args.outdir, exist_ok=True)

    print("\n" + "=" * 70)
    print("ASR COMPARISON: Original vs Optimized Comments")
    print(f"Filter: single-bot, no-upvotes, {args.attack} attack")
    print("Domains: " + ", ".join(sorted(EXAMINED_DOMAINS)))
    print("=" * 70)
    print(comparison.to_string(index=False))
    print("=" * 70)

    csv_path = os.path.join(args.outdir, "asr_comparison_single_bot_no_upvotes.csv")
    comparison.to_csv(csv_path, index=False)
    print(f"\nSaved: {csv_path}")

    # Summary stats
    orig_mean = orig_filtered["judge_score"].mean() * 100
    opt_mean = opt_filtered["judge_score"].mean() * 100
    print(f"\nOverall ASR (single-bot, no-upvotes, {args.attack}):")
    print(f"  Original:  {orig_mean:.1f}% (n={len(orig_filtered)})")
    print(f"  Optimized: {opt_mean:.1f}% (n={len(opt_filtered)})")
    print(f"  Delta:     {opt_mean - orig_mean:+.1f} pp")

    # Chart if matplotlib available
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        fig, ax = plt.subplots(figsize=(10, 6))
        x = range(len(comparison))
        width = 0.35
        ax.bar(
            [i - width / 2 for i in x],
            comparison["Original ASR%"],
            width,
            label="Original",
            color="#4C72B0",
        )
        ax.bar(
            [i + width / 2 for i in x],
            comparison["Optimized ASR%"],
            width,
            label="Optimized",
            color="#55A868",
        )
        ax.set_xticks(x)
        ax.set_xticklabels(comparison["domain"], rotation=45, ha="right")
        ax.set_ylabel("ASR (%)")
        ax.set_title(
            f"ASR Comparison: Original vs Optimized (single-bot, no-upvotes, {args.attack})",
            fontsize=12,
            fontweight="bold",
        )
        ax.legend()
        ax.set_ylim(0, 100)
        plt.tight_layout()
        chart_path = os.path.join(args.outdir, "asr_comparison_chart.png")
        plt.savefig(chart_path, dpi=150)
        plt.close()
        print(f"Chart saved: {chart_path}")
    except ImportError:
        print("(matplotlib not available — skipping chart)")


if __name__ == "__main__":
    main()
