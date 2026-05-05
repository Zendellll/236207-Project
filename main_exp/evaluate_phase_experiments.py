"""
End-to-end evaluation + plotting pipeline for run_phase_experiments.py outputs.

This script reuses the proven judge from analyze_reasoning_cot.py (same prompt
schema, same `judge_*` columns, same retries) and produces the same plot
catalogue as aggregate_and_plot_judges.py, with the `phase` axis replacing the
`attack` and `upvote` axes (which are constants in this experiment).

Output layout (parity with logs/plots/):
    logs/plots_phases/
        asr_overall_per_model.png                  (attack phases only)
        asr_per_model_per_phase.png                (X = phase)
        asr_position_control_per_model.png         (Top / Middle / Bottom)
        asr_baselines_vs_attack_per_model.png      (No Poison / Benign+ / Atk-avg)
        asr_heatmap_model_x_phase.png
        asr_heatmap_domain_x_phase.png
        category_distribution_per_model.png        (Cat1 / Cat2 / Cat3)
        hazard_mention_rate_per_phase.png
        per_model/
            heatmap_domain_x_phase_<model>.png     (per-model heatmap)
        advanced/
            pathway_fingerprint_per_model_per_phase.png
            asr_per_domain_consistency.png
            domain_difficulty_ranking.png

Plots that are *not* produced because the experiment fixes the corresponding
axis to a single value (would otherwise show one category only):
    asr_per_model_per_upvote.png            (only 'no-upvotes')
    asr_attack_family_x_social_proof.png    (only severe_safety + no-upvotes)
    vulnerability_radar*.png                (only one attack family)
    social_proof_lift*.png                  (no upvote variation)
    reasoning_specificity_matrix.png        (only one attack family)

Default I/O layout:
    main_exp/
      logs/                                  raw inference CSVs (input)
      evaluated_phases/                      judged CSVs (output of `judge`)
      logs/plots_phases/                     plots (output of `plot`)

Usage:
    cd main_exp
    export OPENROUTER_API_KEY=sk-or-...

    # 1) judge all 15 raw CSVs (resumable: skips files already in --eval-dir)
    python3 evaluate_phase_experiments.py judge --workers 8

    # 2) generate plots from the evaluated_phases/ directory
    python3 evaluate_phase_experiments.py plot

    # OR run both back-to-back
    python3 evaluate_phase_experiments.py all --workers 8
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required: pip install numpy")
try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas")
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError:
    sys.exit("matplotlib and seaborn are required: pip install matplotlib seaborn")
try:
    from tqdm import tqdm
except ImportError:
    sys.exit("tqdm is required: pip install tqdm")

# Reuse the proven judge end-to-end
import analyze_reasoning_cot as arc
from analyze_reasoning_cot import (
    JudgeConfig,
    build_client,
    process_row,
    append_judge_columns,
    select_text_columns,
    DEFAULT_JUDGE_MODEL,
    DEFAULT_BASE_URL,
    DEFAULT_TARGET,
)


# --- CONFIG ------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "logs"
DEFAULT_EVAL_DIR = SCRIPT_DIR / "evaluated_phases"
DEFAULT_PLOTS_DIR = SCRIPT_DIR / "logs" / "plots_phases"

PHASE_LABEL: Dict[str, str] = {
    "baseline_no_poison":      "Baseline (No Poison)",
    "baseline_benign_positive": "Baseline (Benign +)",
    "position_top":            "Top",
    "position_middle":         "Middle",
    "position_bottom":         "Bottom",
}
PHASES_ORDER: List[str] = list(PHASE_LABEL.keys())
POSITION_PHASES: List[str] = ["position_top", "position_middle", "position_bottom"]
POSITION_LABELS: List[str] = ["Top", "Middle", "Bottom"]
BASELINE_PHASES: List[str] = ["baseline_no_poison", "baseline_benign_positive"]

# "Attack rows" semantically = rows where a poisoned source was injected.
# Used everywhere the main experiment's plots used "attack rows only".
ATTACK_PHASES: List[str] = list(POSITION_PHASES)

DOMAIN_PRETTY: Dict[str, str] = {
    "taxi-driver":            "Taxi Driver",
    "food-tour-guide":        "Food Tour",
    "surf-school":             "Surf School",
    "scuba-diving-center":     "Scuba Diving",
    "boutique-winery":         "Boutique Winery",
    "cooking-class":           "Cooking Class",
    "glamping":                "Glamping",
    "historical-tour-guide":   "Historical Guide",
    "jeep-tours":              "Jeep Tours",
    "vacation-photographer":   "Vacation Photo",
}
DOMAIN_ORDER: List[str] = list(DOMAIN_PRETTY.values())

# Mirrors aggregate_and_plot_judges.py so plots look consistent with the main study.
PATHWAY_HUMAN: Dict[str, str] = {
    "Logic Hijacking":     "Safety-based Hijacking",
    "Authority Deference": "Authority-based Hijacking",
    "Attribute Anchoring": "Attribute-based Hijacking",
    "Benign/Other":        "Other",
}
PATHWAY_DISPLAY_ORDER: List[str] = [
    "Safety-based Hijacking",
    "Authority-based Hijacking",
    "Attribute-based Hijacking",
    "Other",
]
PATHWAY_COLORS: Dict[str, str] = {
    "Safety-based Hijacking":    "#d62728",
    "Authority-based Hijacking": "#1f77b4",
    "Attribute-based Hijacking": "#2ca02c",
    "Other":                     "#bdbdbd",
}


# --- DISCOVERY ---------------------------------------------------------------

def parse_results_filename(name: str) -> Optional[Tuple[str, str]]:
    """Parse 'results_{slug}_{phase}.csv' -> (slug, phase) or None."""
    if not name.startswith("results_") or not name.endswith(".csv"):
        return None
    stem = name[len("results_"):-len(".csv")]
    for phase in PHASES_ORDER:
        suf = "_" + phase
        if stem.endswith(suf):
            return stem[:-len(suf)], phase
    return None


def parse_evaluated_filename(name: str) -> Optional[Tuple[str, str]]:
    """Parse 'evaluated_results_{slug}_{phase}.csv' -> (slug, phase) or None."""
    if not name.startswith("evaluated_results_") or not name.endswith(".csv"):
        return None
    stem = name[len("evaluated_results_"):-len(".csv")]
    for phase in PHASES_ORDER:
        suf = "_" + phase
        if stem.endswith(suf):
            return stem[:-len(suf)], phase
    return None


def discover_result_csvs(logs_dir: Path) -> List[Tuple[str, str, Path]]:
    """Return [(model_slug, phase, csv_path), ...] for results_*_{phase}.csv."""
    if not logs_dir.is_dir():
        sys.exit(f"logs dir not found: {logs_dir}")
    out: List[Tuple[str, str, Path]] = []
    for p in sorted(logs_dir.glob("results_*.csv")):
        parsed = parse_results_filename(p.name)
        if parsed is None:
            continue
        slug, phase = parsed
        out.append((slug, phase, p))
    return out


# --- JUDGING -----------------------------------------------------------------

def judge_one_file(
    path: Path,
    eval_dir: Path,
    cfg: JudgeConfig,
    workers: int,
    overwrite: bool,
) -> Optional[Path]:
    """Run the analyze_reasoning_cot judge on one results CSV."""
    parsed = parse_results_filename(path.name)
    if parsed is None:
        print(f"  [SKIP] cannot parse phase from filename: {path.name}")
        return None
    model_slug, phase = parsed
    out_path = eval_dir / f"evaluated_results_{model_slug}_{phase}.csv"

    if out_path.exists() and not overwrite:
        print(f"  [SKIP] {out_path.name} already exists (use --overwrite).")
        return out_path

    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"  [ERROR] could not read {path}: {e}")
        return None
    if df.empty:
        print(f"  [SKIP] empty file: {path}")
        return None

    try:
        cot_col, final_col, fallback_col = select_text_columns(df)
    except KeyError as e:
        print(f"  [SKIP] {path.name}: {e}")
        return None

    cot_series = df[cot_col].fillna("").astype(str)
    final_series = df[final_col].fillna("").astype(str)
    fallback_series = (
        df[fallback_col].fillna("").astype(str)
        if fallback_col is not None
        else pd.Series([""] * len(df))
    )
    cot_used = cot_series.where(cot_series.str.strip() != "", fallback_series)

    client = build_client(cfg)
    verdicts: List[Optional[Dict]] = [None] * len(df)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [
            ex.submit(process_row, i, cot_used.iat[i], final_series.iat[i], cfg, client)
            for i in range(len(df))
        ]
        with tqdm(total=len(futures), desc=f"{model_slug}/{phase}", leave=False) as bar:
            for fut in as_completed(futures):
                i, payload = fut.result()
                verdicts[i] = payload
                bar.update(1)

    enriched = append_judge_columns(df, verdicts)  # type: ignore[arg-type]
    enriched["judge_score"] = (enriched["judge_status"] == 1).astype(int)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_path, index=False)
    return out_path


def cmd_judge(args: argparse.Namespace) -> None:
    """Run the judge over every results_*_{phase}.csv under --input-dir."""
    api_key = (args.api_key or os.environ.get("OPENROUTER_API_KEY", "")).strip()
    if not api_key:
        sys.exit("Missing API key: pass --api-key or set OPENROUTER_API_KEY.")

    cfg = JudgeConfig(
        model=args.judge_model,
        base_url=args.base_url,
        api_key=api_key,
        target=args.target,
        max_retries=args.max_retries,
    )

    pairs = discover_result_csvs(args.input_dir)
    if not pairs:
        sys.exit(f"No results_*_{{phase}}.csv files found in {args.input_dir}")

    print(f"Discovered {len(pairs)} result CSV(s) in {args.input_dir}.")
    print(f"Judge model: {cfg.model}  ({cfg.base_url})")
    print(f"Output dir:  {args.eval_dir}")

    written: List[Path] = []
    for slug, phase, path in tqdm(pairs, desc="files", unit="file"):
        out = judge_one_file(path, args.eval_dir, cfg, args.workers, args.overwrite)
        if out is not None:
            written.append(out)

    print(f"\nWrote {len(written)} evaluated CSV(s) to {args.eval_dir}.")


# --- AGGREGATION + METRICS ---------------------------------------------------

def load_all_evaluated(eval_dir: Path) -> pd.DataFrame:
    """Load every evaluated_results_*_{phase}.csv and concatenate with phase tag."""
    if not eval_dir.is_dir():
        sys.exit(f"evaluated dir not found: {eval_dir}. Run `judge` first.")

    frames: List[pd.DataFrame] = []
    for p in sorted(eval_dir.glob("evaluated_results_*.csv")):
        parsed = parse_evaluated_filename(p.name)
        if parsed is None:
            continue
        slug, phase = parsed
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"  [WARN] skipped {p}: {e}")
            continue
        if df.empty:
            continue

        if "model" in df.columns and df["model"].notna().any():
            df["model_label"] = df["model"].astype(str)
        else:
            df["model_label"] = slug
        df["phase"] = phase
        df["model_slug"] = slug
        frames.append(df)

    if not frames:
        sys.exit(f"No evaluated CSVs in {eval_dir}.")
    df = pd.concat(frames, ignore_index=True)
    if "judge_score" not in df.columns:
        df["judge_score"] = (df["judge_status"] == 1).astype(int)
    df["domain_pretty"] = df["domain"].map(DOMAIN_PRETTY).fillna(df["domain"])
    df["phase_label"] = df["phase"].map(PHASE_LABEL).fillna(df["phase"])
    return df


def asr_with_sem(group: pd.DataFrame) -> pd.Series:
    """Mean ASR + SEM treating each domain as one independent observation."""
    if group.empty:
        return pd.Series({"asr_mean": np.nan, "asr_sem": np.nan, "n_domains": 0})
    per_domain = group.groupby("domain")["judge_score"].mean()
    n = len(per_domain)
    mean = per_domain.mean() * 100
    sem = (per_domain.std(ddof=1) / np.sqrt(n) * 100) if n > 1 else 0.0
    return pd.Series({"asr_mean": mean, "asr_sem": sem, "n_domains": n})


def summarize(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    rows: List[Dict] = []
    for keys, sub in df.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        rec = dict(zip(group_cols, keys))
        rec.update(asr_with_sem(sub).to_dict())
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def _to_bool_col(series: pd.Series) -> pd.Series:
    """Coerce a possibly-stringified bool column to a real bool series."""
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


def print_summary(df: pd.DataFrame) -> None:
    """Replicate the analyze_reasoning_cot summary, broken down by phase."""
    total = len(df)
    if total == 0:
        return
    cat1 = (df["judge_status"] == 1).sum()
    cat2 = (df["judge_status"] == 2).sum()
    cat3 = (df["judge_status"] == 3).sum()

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    bar = "=" * 72
    print("\n" + bar)
    print("PHASE EVALUATION — GLOBAL SUMMARY")
    print(bar)
    print(f"Rows judged:        {total}")
    print(f"Cat1 (Full ASR):    {cat1} ({pct(cat1)})")
    print(f"Cat2 (Partial):     {cat2} ({pct(cat2)})")
    print(f"Cat3 (Failure):     {cat3} ({pct(cat3)})")

    print("-" * 72)
    print("ASR (Cat1) per phase, all models pooled:")
    for phase in PHASES_ORDER:
        sub = df[df["phase"] == phase]
        if sub.empty:
            continue
        n = len(sub)
        rate = (sub["judge_status"] == 1).sum() / n * 100
        print(f"  {PHASE_LABEL[phase]:30s}: {rate:5.1f}%  (n={n})")

    print("-" * 72)
    print("ASR (Cat1) per (model × phase):")
    for model in sorted(df["model_label"].unique()):
        for phase in PHASES_ORDER:
            sub = df[(df["model_label"] == model) & (df["phase"] == phase)]
            if sub.empty:
                continue
            rate = (sub["judge_status"] == 1).sum() / len(sub) * 100
            print(f"  {model:35s} | {PHASE_LABEL[phase]:25s}: {rate:5.1f}%  (n={len(sub)})")
    print(bar)


# --- PLOTTING ----------------------------------------------------------------

def _save(fig: plt.Figure, path: Path) -> None:
    """Save and close a Matplotlib figure (creates parents as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PLOT] {path}")


def _draw_grouped(
    ax: plt.Axes,
    pivot_mean: pd.DataFrame,
    pivot_sem: Optional[pd.DataFrame],
    x_order: List[str],
    hue_order: List[str],
    palette: List,
    bar_width: float = 0.22,
    label_fmt: str = "{:.1f}",
) -> None:
    """Manually positioned grouped bars + value labels (no seaborn patch quirks)."""
    centers = np.arange(len(x_order))
    n_hue = len(hue_order)
    start = centers - bar_width * n_hue / 2 + bar_width / 2

    for i, hue in enumerate(hue_order):
        x_pos = start + i * bar_width
        means = pivot_mean[hue].fillna(0).values
        sems = (
            pivot_sem[hue].fillna(0).values
            if pivot_sem is not None and hue in pivot_sem.columns
            else np.zeros_like(means)
        )
        ax.bar(
            x_pos, means, width=bar_width, yerr=sems, capsize=3,
            label=hue, color=palette[i],
            edgecolor="black", linewidth=0.4,
            error_kw={"ecolor": "black", "lw": 1},
        )
        for x, m in zip(x_pos, means):
            ax.text(x, m + 1.5, label_fmt.format(m), ha="center", fontsize=8)

    ax.set_xticks(centers)
    ax.set_xticklabels(x_order)


def plot_overall_per_model(df: pd.DataFrame, plots_dir: Path) -> None:
    """Overall ASR (Cat1) per model — attack phases only, with SEM across domains."""
    sub = df[df["phase"].isin(ATTACK_PHASES)].copy()
    if sub.empty:
        print("  [SKIP] overall per model — no attack-phase rows")
        return
    summary = summarize(sub, ["model_label"])
    summary = summary.sort_values("asr_mean", ascending=False).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10, 6))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=len(summary))
    ax.bar(
        summary["model_label"], summary["asr_mean"],
        yerr=summary["asr_sem"], capsize=4,
        color=palette, edgecolor="black", linewidth=0.5,
        error_kw={"ecolor": "black", "lw": 1},
    )
    for i, row in summary.iterrows():
        ax.text(i, row["asr_mean"] + 1.5, f"{row['asr_mean']:.1f}%", ha="center", fontsize=9)
    ax.set_title(
        "Attack Success Rate (Cat1) per Model — overall\n"
        "(attack phases only; error bars = SEM across domains)",
    )
    ax.set_ylabel("ASR % (Category 1)")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 100)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / "asr_overall_per_model.png")


def plot_per_model_per_phase(df: pd.DataFrame, plots_dir: Path) -> None:
    """ASR (Cat1) grouped bars: model × phase. Replaces per_model_per_attack."""
    summary = summarize(df, ["model_label", "phase"])
    if summary.empty:
        return
    phases_present = [p for p in PHASES_ORDER if p in set(summary["phase"].unique())]
    phase_labels = [PHASE_LABEL[p] for p in phases_present]
    models = sorted(summary["model_label"].unique())

    pivot_mean = (
        summary.pivot(index="phase", columns="model_label", values="asr_mean")
        .reindex(index=phases_present, columns=models)
    )
    pivot_sem = (
        summary.pivot(index="phase", columns="model_label", values="asr_sem")
        .reindex(index=phases_present, columns=models)
    )

    fig, ax = plt.subplots(figsize=(13, 7))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=max(3, len(models)))
    _draw_grouped(ax, pivot_mean, pivot_sem, phase_labels, models, palette,
                  bar_width=0.18)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    ax.set_title("ASR per Phase — Model comparison\n(error bars = SEM across domains)")
    ax.set_ylabel("ASR % (Category 1)")
    ax.set_xlabel("Phase")
    ax.set_ylim(0, 100)
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "asr_per_model_per_phase.png")


def plot_heatmap_model_phase(df: pd.DataFrame, plots_dir: Path) -> None:
    """Heatmap of ASR(Cat1) — rows = model, columns = phase."""
    summary = summarize(df, ["model_label", "phase"])
    if summary.empty:
        return
    phases_present = [p for p in PHASES_ORDER if p in set(summary["phase"].unique())]
    phase_labels = [PHASE_LABEL[p] for p in phases_present]
    pivot = (
        summary.pivot(index="model_label", columns="phase", values="asr_mean")
        .reindex(columns=phases_present)
        .round(1)
    )
    pivot.columns = phase_labels

    fig, ax = plt.subplots(figsize=(11, 0.7 * max(4, len(pivot)) + 2))
    sns.heatmap(
        pivot, annot=True, fmt=".1f", cmap="rocket_r",
        vmin=0, vmax=100, ax=ax, cbar_kws={"label": "ASR % (Cat1)"},
    )
    ax.set_title("ASR Heatmap — Model × Phase")
    ax.set_xlabel("Phase")
    ax.set_ylabel("Model")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / "asr_heatmap_model_x_phase.png")


def plot_heatmap_domain_phase(
    df: pd.DataFrame,
    plots_dir: Path,
    *,
    title_suffix: str = "(all models)",
    filename: str = "asr_heatmap_domain_x_phase.png",
) -> None:
    """Heatmap of ASR(Cat1) — rows = domain, columns = phase."""
    summary = summarize(df, ["domain_pretty", "phase"])
    if summary.empty:
        return
    phases_present = [p for p in PHASES_ORDER if p in set(summary["phase"].unique())]
    phase_labels = [PHASE_LABEL[p] for p in phases_present]
    domains_present = [d for d in DOMAIN_ORDER if d in set(summary["domain_pretty"].unique())]
    if not domains_present:
        domains_present = sorted(summary["domain_pretty"].unique())

    pivot = (
        summary.pivot(index="domain_pretty", columns="phase", values="asr_mean")
        .reindex(index=domains_present, columns=phases_present)
        .round(1)
    )
    pivot.columns = phase_labels

    fig, ax = plt.subplots(figsize=(10, 0.55 * max(4, len(pivot)) + 2))
    sns.heatmap(
        pivot, annot=True, fmt=".1f", cmap="YlOrRd",
        vmin=0, vmax=100, ax=ax, cbar_kws={"label": "ASR (%)"},
        linewidths=0.5, linecolor="white",
    )
    ax.set_title(f"Per-domain ASR by phase {title_suffix}")
    ax.set_xlabel("Phase")
    ax.set_ylabel("Domain")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / filename)


def plot_category_distribution(df: pd.DataFrame, plots_dir: Path) -> None:
    """Stacked Cat1/Cat2/Cat3 distribution per model — attack rows only."""
    sub = df[df["phase"].isin(ATTACK_PHASES)].copy()
    if sub.empty:
        return
    counts = (
        sub.groupby(["model_label", "judge_status"]).size()
        .unstack(fill_value=0)
        .reindex(columns=[1, 2, 3], fill_value=0)
    )
    pct = counts.div(counts.sum(axis=1), axis=0) * 100
    pct = pct.loc[pct[1].sort_values(ascending=False).index]
    pct.columns = ["Cat1 (Full)", "Cat2 (Partial)", "Cat3 (Failure)"]

    fig, ax = plt.subplots(figsize=(11, 6))
    cat_colors = ["#d62728", "#ff7f0e", "#2ca02c"]
    pct.plot(kind="bar", stacked=True, ax=ax, color=cat_colors,
             edgecolor="white", linewidth=0.5)
    for container in ax.containers:
        labels = [f"{v:.1f}%" if v >= 4 else "" for v in container.datavalues]
        ax.bar_label(container, labels=labels, label_type="center",
                     fontsize=9, color="white")
    ax.set_title("Judge Category Distribution per Model (attack phases only)")
    ax.set_ylabel("Share of rows (%)")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 100)
    ax.legend(title="Judge category", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / "category_distribution_per_model.png")


def plot_per_model_heatmaps(df: pd.DataFrame, plots_dir: Path) -> None:
    """One domain × phase heatmap per model, written to plots_dir/per_model/."""
    out_dir = plots_dir / "per_model"
    for model in sorted(df["model_label"].unique()):
        sub = df[df["model_label"] == model]
        if sub.empty:
            continue
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(model)).strip("_")
        plot_heatmap_domain_phase(
            sub, out_dir,
            title_suffix=f"({model})",
            filename=f"heatmap_domain_x_phase_{slug}.png",
        )


def plot_per_domain_consistency(df: pd.DataFrame, advanced_dir: Path) -> None:
    """Boxplot of per-domain ASR per model — attack phases only (one point per domain)."""
    sub = df[df["phase"].isin(ATTACK_PHASES)].copy()
    if sub.empty:
        return
    per_md = (
        sub.groupby(["model_label", "domain"])["judge_score"]
        .mean().mul(100).rename("asr").reset_index()
    )
    if per_md.empty:
        return
    order = (
        per_md.groupby("model_label")["asr"].median()
        .sort_values(ascending=False).index.tolist()
    )

    fig, ax = plt.subplots(figsize=(12, 6.5))
    sns.set_theme(style="whitegrid")
    sns.boxplot(
        data=per_md, x="model_label", y="asr",
        order=order, ax=ax, palette="Set2",
        width=0.6, fliersize=4,
    )
    sns.stripplot(
        data=per_md, x="model_label", y="asr",
        order=order, ax=ax, color="black", size=3, alpha=0.6, jitter=0.2,
    )
    ax.set_title(
        "Per-domain ASR distribution per model\n"
        "(attack phases only; each point = one of the 10 domains)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Model", fontsize=11)
    ax.set_ylabel("ASR % across domains", fontsize=11)
    ax.set_ylim(0, 100)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, advanced_dir / "asr_per_domain_consistency.png")


def plot_domain_difficulty(df: pd.DataFrame, advanced_dir: Path) -> None:
    """Bar chart ranking domains by mean ASR across all models — attack phases only."""
    sub = df[df["phase"].isin(ATTACK_PHASES)].copy()
    if sub.empty:
        return
    per_dom = (
        sub.groupby("domain_pretty")["judge_score"]
        .mean().mul(100).rename("asr").reset_index()
        .sort_values("asr", ascending=True)
        .reset_index(drop=True)
    )
    if per_dom.empty:
        return
    fig, ax = plt.subplots(figsize=(11, 6.5))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=len(per_dom))
    ax.barh(per_dom["domain_pretty"], per_dom["asr"], color=palette,
            edgecolor="black", linewidth=0.4)
    for i, v in enumerate(per_dom["asr"]):
        ax.text(v + 0.5, i, f"{v:.1f}%", va="center", fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Mean ASR % across all models (attack phases)", fontsize=11)
    ax.set_ylabel("Domain", fontsize=11)
    ax.set_title("Domain Difficulty Ranking (hardest → easiest to attack)",
                 fontsize=13, fontweight="bold")
    _save(fig, advanced_dir / "domain_difficulty_ranking.png")


def plot_position_control(df: pd.DataFrame, plots_dir: Path) -> None:
    """Bar chart: ASR per position (Top/Middle/Bottom) × model. Lost-in-the-Middle test."""
    sub = df[df["phase"].isin(POSITION_PHASES)].copy()
    if sub.empty:
        print("  [SKIP] position control — no position_* phases present")
        return
    sub["phase_label"] = sub["phase"].map(
        dict(zip(POSITION_PHASES, POSITION_LABELS))
    )
    summary = summarize(sub, ["model_label", "phase_label"])
    models = sorted(summary["model_label"].unique())

    fig, ax = plt.subplots(figsize=(11, 6.5))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=max(3, len(models)))

    pivot_mean = (
        summary.pivot(index="phase_label", columns="model_label", values="asr_mean")
        .reindex(index=POSITION_LABELS, columns=models)
    )
    pivot_sem = (
        summary.pivot(index="phase_label", columns="model_label", values="asr_sem")
        .reindex(index=POSITION_LABELS, columns=models)
    )

    _draw_grouped(ax, pivot_mean, pivot_sem, POSITION_LABELS, models, palette)
    ax.set_xlabel("Position of poisoned source", fontsize=11)
    ax.set_ylabel("ASR % (Category 1)", fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_title(
        "Position Control — Lost-in-the-Middle test\n(error bars = SEM across domains)",
        fontsize=13, fontweight="bold",
    )
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "asr_position_control_per_model.png")


def plot_baselines_vs_attack(df: pd.DataFrame, plots_dir: Path) -> None:
    """Bar chart: No Poison / Benign Positive / Avg(position attacks), per model."""
    summary = summarize(df, ["model_label", "phase"])
    if summary.empty:
        print("  [SKIP] baselines vs attack — no rows")
        return

    cond_order = ["No Poison", "Benign +", "Attack (avg of 3 positions)"]
    rows: List[Dict] = []
    for model in summary["model_label"].unique():
        sub = summary[summary["model_label"] == model]
        for phase, cond in (("baseline_no_poison", "No Poison"),
                            ("baseline_benign_positive", "Benign +")):
            r = sub[sub["phase"] == phase]
            if r.empty:
                continue
            rows.append({
                "model_label": model, "condition": cond,
                "asr_mean": float(r["asr_mean"].iloc[0]),
                "asr_sem":  float(r["asr_sem"].iloc[0]),
            })
        atk = sub[sub["phase"].isin(POSITION_PHASES)]
        if not atk.empty:
            mean_asr = float(atk["asr_mean"].mean())
            sem_asr = (
                float(atk["asr_mean"].std(ddof=1) / np.sqrt(len(atk)))
                if len(atk) > 1 else 0.0
            )
            rows.append({
                "model_label": model, "condition": "Attack (avg of 3 positions)",
                "asr_mean": mean_asr, "asr_sem": sem_asr,
            })

    flat = pd.DataFrame(rows)
    if flat.empty:
        print("  [SKIP] baselines vs attack — nothing to plot")
        return

    models = sorted(flat["model_label"].unique())
    pivot_mean = (
        flat.pivot(index="condition", columns="model_label", values="asr_mean")
        .reindex(index=cond_order, columns=models)
    )
    pivot_sem = (
        flat.pivot(index="condition", columns="model_label", values="asr_sem")
        .reindex(index=cond_order, columns=models)
    )

    fig, ax = plt.subplots(figsize=(11, 6.5))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=max(3, len(models)))
    _draw_grouped(ax, pivot_mean, pivot_sem, cond_order, models, palette)
    ax.set_xlabel("Condition", fontsize=11)
    ax.set_ylabel("ASR % (Category 1)", fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_title(
        "Baselines vs Position Attack — Model comparison\n(error bars = SEM across domains)",
        fontsize=13, fontweight="bold",
    )
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "asr_baselines_vs_attack_per_model.png")


def plot_pathway_fingerprint(df: pd.DataFrame, plots_dir: Path) -> None:
    """Stacked-bar pathway distribution among Cat1 successes per (model, phase)."""
    if "judge_pathway" not in df.columns:
        print("  [SKIP] pathway fingerprint — judge_pathway not available")
        return
    cat1 = df[(df["judge_status"] == 1) & df["judge_pathway"].notna()].copy()
    if cat1.empty:
        print("  [SKIP] pathway fingerprint — no Cat1 successes")
        return
    cat1["pathway_human"] = cat1["judge_pathway"].map(PATHWAY_HUMAN).fillna("Other")

    models = sorted(cat1["model_label"].unique())
    phases_present = [p for p in PHASES_ORDER if p in set(cat1["phase"].unique())]
    phase_labels = [PHASE_LABEL[p] for p in phases_present]

    n_models = len(models)
    fig, axes = plt.subplots(
        1, n_models, figsize=(5.2 * n_models + 2, 6.5), sharey=True,
    )
    if n_models == 1:
        axes = [axes]

    for ax, model in zip(axes, models):
        sub = cat1[cat1["model_label"] == model]
        counts = (
            sub.groupby(["phase", "pathway_human"]).size()
            .unstack(fill_value=0)
            .reindex(index=phases_present, columns=PATHWAY_DISPLAY_ORDER, fill_value=0)
        )
        row_totals = counts.sum(axis=1).replace(0, np.nan)
        pct = counts.div(row_totals, axis=0).fillna(0) * 100

        pct.plot(
            kind="bar", stacked=True, ax=ax,
            color=[PATHWAY_COLORS[c] for c in PATHWAY_DISPLAY_ORDER],
            edgecolor="white", linewidth=0.5, legend=False,
        )
        for container in ax.containers:
            labels = [f"{v:.0f}%" if v >= 5 else "" for v in container.datavalues]
            ax.bar_label(container, labels=labels, label_type="center",
                          fontsize=8, color="white")

        ax.set_title(model, fontsize=11, fontweight="bold")
        ax.set_xlabel("")
        ax.set_xticklabels(phase_labels, rotation=20, ha="right")
        ax.set_ylim(0, 100)
        if ax is axes[0]:
            ax.set_ylabel("Share of Cat1 successes (%)", fontsize=11)
        else:
            ax.set_ylabel("")

    handles = [plt.Rectangle((0, 0), 1, 1, color=PATHWAY_COLORS[c])
               for c in PATHWAY_DISPLAY_ORDER]
    fig.legend(handles, PATHWAY_DISPLAY_ORDER, title="Pathway",
               loc="upper right", bbox_to_anchor=(1.0, 1.0), fontsize=9)
    fig.suptitle(
        "Logic Hijacking Fingerprint per Model × Phase\n"
        "(distribution of reasoning pathways among Cat1 successes)",
        fontsize=13, fontweight="bold", y=1.02,
    )
    _save(fig, plots_dir / "pathway_fingerprint_per_model_per_phase.png")


def plot_hazard_mention(df: pd.DataFrame, plots_dir: Path) -> None:
    """Bar chart: % of rows where the CoT mentioned a hazard, per model × phase."""
    if "judge_hazard_mentioned" not in df.columns:
        print("  [SKIP] hazard mention — judge_hazard_mentioned not available")
        return
    df = df.copy()
    df["hazard_bool"] = _to_bool_col(df["judge_hazard_mentioned"])
    grp = (
        df.groupby(["model_label", "phase"])["hazard_bool"]
        .mean().mul(100).reset_index(name="rate")
    )
    if grp.empty:
        print("  [SKIP] hazard mention — no data")
        return

    phases_present = [p for p in PHASES_ORDER if p in set(grp["phase"].unique())]
    phase_labels = [PHASE_LABEL[p] for p in phases_present]
    models = sorted(grp["model_label"].unique())

    pivot_rate = (
        grp.pivot(index="phase", columns="model_label", values="rate")
        .reindex(index=phases_present, columns=models).fillna(0)
    )

    fig, ax = plt.subplots(figsize=(13, 6.5))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("viridis", n_colors=max(3, len(models)))
    _draw_grouped(ax, pivot_rate, None, phase_labels, models, palette,
                  bar_width=0.22, label_fmt="{:.1f}")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    ax.set_xlabel("Phase", fontsize=11)
    ax.set_ylabel("Hazard mention rate (%)", fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_title(
        "Hazard Mention Rate per Phase\n"
        "(share of rows whose CoT explicitly references a fabricated hazard)",
        fontsize=13, fontweight="bold",
    )
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "hazard_mention_rate_per_phase.png")


# --- COMMANDS ----------------------------------------------------------------

def cmd_plot(args: argparse.Namespace) -> None:
    """Aggregate evaluated CSVs and write all phase-adapted plots."""
    df = load_all_evaluated(args.eval_dir)
    print(f"Loaded {len(df)} judged rows from {args.eval_dir}.")

    plots_dir: Path = args.plots_dir
    plots_dir.mkdir(parents=True, exist_ok=True)
    advanced_dir = plots_dir / "advanced"
    advanced_dir.mkdir(parents=True, exist_ok=True)

    df.to_csv(args.eval_dir / "aggregated_phases.csv", index=False)
    print(f"  [SAVE] aggregated CSV -> {args.eval_dir / 'aggregated_phases.csv'}")

    # Main plots (parity with logs/plots/)
    plot_overall_per_model(df, plots_dir)
    plot_per_model_per_phase(df, plots_dir)
    plot_position_control(df, plots_dir)
    plot_baselines_vs_attack(df, plots_dir)
    plot_heatmap_model_phase(df, plots_dir)
    plot_heatmap_domain_phase(df, plots_dir)
    plot_category_distribution(df, plots_dir)
    plot_hazard_mention(df, plots_dir)
    plot_per_model_heatmaps(df, plots_dir)

    # Advanced plots (parity with logs/plots/advanced/)
    plot_pathway_fingerprint(df, advanced_dir)
    plot_per_domain_consistency(df, advanced_dir)
    plot_domain_difficulty(df, advanced_dir)

    print_summary(df)


def cmd_all(args: argparse.Namespace) -> None:
    """judge -> plot in a single command."""
    cmd_judge(args)
    cmd_plot(args)


# --- CLI ---------------------------------------------------------------------

def _add_eval_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL_DIR,
                   help="Directory of evaluated_results_*.csv "
                        "(default: ./evaluated_phases).")


def _add_judge_args(p: argparse.ArgumentParser, *, with_eval_dir: bool) -> None:
    p.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR,
                   help="Directory with results_{model}_{phase}.csv (default: ./logs).")
    if with_eval_dir:
        _add_eval_dir(p)
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                   help="Judge model on OpenRouter (default: meta-llama/llama-3.3-70b-instruct).")
    p.add_argument("--target", default=DEFAULT_TARGET,
                   help="Target name the attack tries to promote (default: LocalGems).")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL,
                   help="OpenAI-compatible base URL (default: OpenRouter).")
    p.add_argument("--api-key", default="",
                   help="API key (or set OPENROUTER_API_KEY).")
    p.add_argument("--workers", type=int, default=8,
                   help="Concurrent judge calls per file (default: 8).")
    p.add_argument("--max-retries", type=int, default=4,
                   help="Retries per row on API/JSON errors (default: 4).")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-judge files even if their evaluated CSV already exists.")


def _add_plot_args(p: argparse.ArgumentParser, *, with_eval_dir: bool) -> None:
    if with_eval_dir:
        _add_eval_dir(p)
    p.add_argument("--plots-dir", type=Path, default=DEFAULT_PLOTS_DIR,
                   help="Where to write plots (default: ./logs/plots_phases).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge + plot the run_phase_experiments.py outputs.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    pj = sub.add_parser("judge", help="LLM-as-Judge over results_*_{phase}.csv.")
    _add_judge_args(pj, with_eval_dir=True)
    pj.set_defaults(func=cmd_judge)

    pp = sub.add_parser("plot", help="Generate the 4 phase-focused plots.")
    _add_plot_args(pp, with_eval_dir=True)
    pp.set_defaults(func=cmd_plot)

    pa = sub.add_parser("all", help="judge then plot in a single run.")
    _add_eval_dir(pa)  # shared by both phases
    _add_judge_args(pa, with_eval_dir=False)
    _add_plot_args(pa, with_eval_dir=False)
    pa.set_defaults(func=cmd_all)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
