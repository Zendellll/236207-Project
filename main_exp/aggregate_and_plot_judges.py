"""
Aggregate per-model judged CSVs and produce model-vs-model plots.

Input layout (default):
    logs/<Model>/judged_<...>.csv
Each CSV is the output of run_judge.py and has at least:
    domain, bot_group, upvote, attack, model, query_id,
    judge_category (1/2/3), judge_score (1 iff category==1)

Outputs:
    logs/aggregated_judged.csv           (one row per query, with model_label)
    logs/plots/asr_overall_per_model.png
    logs/plots/asr_per_model_per_attack.png
    logs/plots/asr_per_model_per_upvote.png
    logs/plots/asr_heatmap_model_x_attack.png
    logs/plots/category_distribution_per_model.png

ASR here = mean of judge_score (Category 1 only). Error bars = SEM across
domains (each domain is treated as one independent draw to reflect dataset
variance, not query-level noise within a domain).

Usage:
    python aggregate_and_plot_judges.py
    python aggregate_and_plot_judges.py --logs-dir logs --output-csv logs/aggregated_judged.csv
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas")
try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required: pip install numpy")
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError:
    sys.exit("matplotlib/seaborn are required: pip install matplotlib seaborn")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LOGS_DIR = SCRIPT_DIR / "logs"
DEFAULT_OUT_CSV = DEFAULT_LOGS_DIR / "aggregated_judged.csv"
DEFAULT_PLOTS_DIR = DEFAULT_LOGS_DIR / "plots"
DEFAULT_EVALUATED_DIR = SCRIPT_DIR / "evaluated_logs"
ADVANCED_SUBDIR = "advanced"

EXCLUDED_FOLDERS = {"logs_new_structure", "poison-percent-ablation", "plots"}

PATHWAY_HUMAN: Dict[str, str] = {
    "Logic Hijacking": "Safety-based Hijacking",
    "Authority Deference": "Authority-based Hijacking",
    "Attribute Anchoring": "Attribute-based Hijacking",
    "Benign/Other": "Other",
}
PATHWAY_DISPLAY_ORDER = [
    "Safety-based Hijacking",
    "Authority-based Hijacking",
    "Attribute-based Hijacking",
    "Other",
]
PATHWAY_COLORS = {
    "Safety-based Hijacking": "#d62728",
    "Authority-based Hijacking": "#1f77b4",
    "Attribute-based Hijacking": "#2ca02c",
    "Other": "#bdbdbd",
}

ATTACK_FAMILY_LABEL: Dict[str, str] = {
    "attribute": "Attribute",
    "fake_authority": "Authority",
    "severe_safety": "Safety",
}
ATTACK_FAMILY_ORDER = ["Attribute", "Authority", "Safety"]

UPVOTE_LABEL: Dict[str, str] = {
    "no-upvotes": "None",
    "low-fake-upvotes": "Low",
    "high-fake-upvotes": "High",
}
UPVOTE_ORDER = ["None", "Low", "High"]
UPVOTE_COLORS = {"None": "#7f9bc5", "Low": "#e08741", "High": "#cf6db4"}

DOMAIN_PRETTY: Dict[str, str] = {
    "taxi-driver": "Taxi Driver",
    "food-tour-guide": "Food Tour",
    "surf-school": "Surf School",
    "scuba-diving-center": "Scuba Diving",
    "boutique-winery": "Boutique Winery",
    "cooking-class": "Cooking Class",
    "glamping": "Glamping",
    "historical-tour-guide": "Historical Guide",
    "jeep-tours": "Jeep Tours",
    "vacation-photographer": "Vacation Photo",
}
DOMAIN_ORDER = list(DOMAIN_PRETTY.values())


# --- DISCOVERY ---

def discover_judged_csvs(logs_dir: Path) -> List[Tuple[str, Path]]:
    """Return [(model_label, csv_path), ...] for every model folder under logs_dir."""
    if not logs_dir.is_dir():
        sys.exit(f"Logs dir not found: {logs_dir}")

    pairs: List[Tuple[str, Path]] = []
    for sub in sorted(p for p in logs_dir.iterdir() if p.is_dir()):
        if sub.name in EXCLUDED_FOLDERS:
            continue
        candidates = sorted(sub.glob("judged_*.csv"))
        if not candidates:
            continue
        pairs.append((sub.name, candidates[0]))
    return pairs


# --- LOADING ---

REQUIRED_COLS = ["domain", "bot_group", "upvote", "attack", "model",
                 "query_id", "judge_category", "judge_score"]


def load_judged(model_label: str, csv_path: Path) -> pd.DataFrame:
    """Load one judged CSV and tag it with model_label; keep only attack rows."""
    df = pd.read_csv(csv_path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"{csv_path}: missing columns {missing}")
    df = df.copy()
    df["model_label"] = model_label
    df["attack"] = df["attack"].fillna("clean")
    df["attack_family"] = df["attack"].map(ATTACK_FAMILY_LABEL).fillna(df["attack"])
    df["social_proof"] = df["upvote"].map(UPVOTE_LABEL).fillna(df["upvote"])
    df["domain_pretty"] = df["domain"].map(DOMAIN_PRETTY).fillna(df["domain"])
    return df


def load_all(logs_dir: Path) -> pd.DataFrame:
    """Concatenate all per-model judged CSVs into one DataFrame."""
    pairs = discover_judged_csvs(logs_dir)
    if not pairs:
        sys.exit(f"No judged_*.csv files found in any model folder under {logs_dir}")

    frames = []
    for label, path in pairs:
        try:
            frames.append(load_judged(label, path))
            print(f"  [LOAD] {label}: {path.name}")
        except Exception as e:
            print(f"  [WARN] skipped {path}: {e}")

    if not frames:
        sys.exit("No usable judged CSVs.")

    df = pd.concat(frames, ignore_index=True)
    df = df[df["judge_score"].isin([0, 1])]
    return df


# --- METRICS (mean +- SEM across domains) ---

def asr_with_sem(group: pd.DataFrame) -> pd.Series:
    """Compute ASR mean and SEM treating each domain as an independent observation."""
    if group.empty:
        return pd.Series({"asr_mean": np.nan, "asr_sem": np.nan, "n_domains": 0})
    per_domain = group.groupby("domain")["judge_score"].mean()
    n = len(per_domain)
    mean = per_domain.mean() * 100
    sem = (per_domain.std(ddof=1) / np.sqrt(n) * 100) if n > 1 else 0.0
    return pd.Series({"asr_mean": mean, "asr_sem": sem, "n_domains": n})


def summarize_groups(df: pd.DataFrame, group_cols: List[str]) -> pd.DataFrame:
    """Group by columns and return ASR with SEM across domains within each cell."""
    rows = []
    for keys, sub in df.groupby(group_cols, dropna=False, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        rec = dict(zip(group_cols, keys))
        rec.update(asr_with_sem(sub).to_dict())
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def grouped_bars(
    summary: pd.DataFrame,
    x_col: str,
    hue_col: str,
    x_order: List[str],
    hue_order: List[str],
    ax: plt.Axes,
    bar_width: float = 0.13,
) -> None:
    """Draw grouped bars with SEM error bars, manually positioned for safety."""
    palette = sns.color_palette("tab10", n_colors=len(hue_order))
    pivot_mean = summary.pivot(index=x_col, columns=hue_col, values="asr_mean").reindex(
        index=x_order, columns=hue_order
    )
    pivot_sem = summary.pivot(index=x_col, columns=hue_col, values="asr_sem").reindex(
        index=x_order, columns=hue_order
    )

    n_hue = len(hue_order)
    centers = np.arange(len(x_order))
    total_w = bar_width * n_hue
    start = centers - total_w / 2 + bar_width / 2

    for i, hue in enumerate(hue_order):
        x_pos = start + i * bar_width
        means = pivot_mean[hue].fillna(0).values
        sems = pivot_sem[hue].fillna(0).values
        ax.bar(
            x_pos, means, width=bar_width,
            yerr=sems, capsize=3,
            label=hue, color=palette[i],
            edgecolor="black", linewidth=0.4,
            error_kw={"ecolor": "black", "lw": 1},
        )

    ax.set_xticks(centers)
    ax.set_xticklabels(x_order)


# --- PLOTTING ---

def _save(fig: plt.Figure, path: Path) -> None:
    """Save a Matplotlib figure to disk and close it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  [PLOT] {path}")


def plot_overall(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """ASR (Cat1) per model — overall, with SEM across domains."""
    summary = summarize_groups(df_attack, ["model_label"])
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
    ax.set_title("Attack Success Rate (Cat1) per Model — overall\n(error bars = SEM across domains)")
    ax.set_ylabel("ASR % (Category 1)")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 100)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / "asr_overall_per_model.png")


def plot_per_attack(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """ASR (Cat1) per model × attack with SEM error bars."""
    summary = summarize_groups(df_attack, ["model_label", "attack"])
    attacks = sorted(summary["attack"].unique())
    models = sorted(summary["model_label"].unique())

    fig, ax = plt.subplots(figsize=(13, 7))
    sns.set_theme(style="whitegrid")
    grouped_bars(
        summary=summary, x_col="attack", hue_col="model_label",
        x_order=attacks, hue_order=models, ax=ax,
    )
    ax.set_title("ASR per Attack — Model comparison\n(error bars = SEM across domains)")
    ax.set_ylabel("ASR % (Category 1)")
    ax.set_xlabel("Attack")
    ax.set_ylim(0, 100)
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "asr_per_model_per_attack.png")


def plot_per_upvote(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """ASR (Cat1) per model × upvote level with SEM error bars."""
    upvote_order = ["no-upvotes", "low-fake-upvotes", "high-fake-upvotes"]
    df = df_attack[df_attack["upvote"].isin(upvote_order)].copy()

    summary = summarize_groups(df, ["model_label", "upvote"])
    models = sorted(summary["model_label"].unique())

    fig, ax = plt.subplots(figsize=(13, 7))
    sns.set_theme(style="whitegrid")
    grouped_bars(
        summary=summary, x_col="upvote", hue_col="model_label",
        x_order=upvote_order, hue_order=models, ax=ax,
    )
    ax.set_title("ASR per Upvote level — Model comparison\n(error bars = SEM across domains)")
    ax.set_ylabel("ASR % (Category 1)")
    ax.set_xlabel("Upvote level")
    ax.set_ylim(0, 100)
    ax.legend(title="Model", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    _save(fig, plots_dir / "asr_per_model_per_upvote.png")


def plot_heatmap(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """Heatmap of ASR(Cat1) — rows = model, columns = attack."""
    summary = summarize_groups(df_attack, ["model_label", "attack"])
    pivot = summary.pivot(index="model_label", columns="attack", values="asr_mean").round(1)

    fig, ax = plt.subplots(figsize=(10, 0.7 * max(4, len(pivot)) + 2))
    sns.heatmap(
        pivot, annot=True, fmt=".1f", cmap="rocket_r",
        vmin=0, vmax=100, ax=ax, cbar_kws={"label": "ASR % (Cat1)"},
    )
    ax.set_title("ASR Heatmap — Model × Attack")
    ax.set_xlabel("Attack")
    ax.set_ylabel("Model")
    _save(fig, plots_dir / "asr_heatmap_model_x_attack.png")


def plot_domain_attack_heatmap(
    df_attack: pd.DataFrame,
    plots_dir: Path,
    title_suffix: str = "(all models)",
    filename: str = "asr_heatmap_domain_x_attack.png",
) -> None:
    """Heatmap ASR(Cat1) — rows = domain, columns = attack family."""
    summary = summarize_groups(df_attack, ["domain_pretty", "attack_family"])
    domain_order = [d for d in DOMAIN_ORDER if d in summary["domain_pretty"].unique()]
    pivot = (
        summary.pivot(index="domain_pretty", columns="attack_family", values="asr_mean")
        .reindex(index=domain_order, columns=ATTACK_FAMILY_ORDER)
        .round(1)
    )
    fig, ax = plt.subplots(figsize=(8, 0.55 * max(4, len(pivot)) + 2))
    sns.heatmap(
        pivot, annot=True, fmt=".1f", cmap="YlOrRd",
        vmin=0, vmax=100, ax=ax, cbar_kws={"label": "ASR (%)"},
        linewidths=0.5, linecolor="white",
    )
    ax.set_title(f"Per-domain ASR by attack family {title_suffix}")
    ax.set_xlabel("Attack family")
    ax.set_ylabel("Domain")
    _save(fig, plots_dir / filename)


def plot_attack_family_social_proof(
    df_attack: pd.DataFrame,
    plots_dir: Path,
    title_suffix: str = "(all models)",
    filename: str = "asr_attack_family_x_social_proof.png",
) -> None:
    """Bar chart ASR(Cat1) per attack family × social proof level."""
    df = df_attack[df_attack["social_proof"].isin(UPVOTE_ORDER)].copy()
    summary = summarize_groups(df, ["attack_family", "social_proof"])

    pivot_mean = (
        summary.pivot(index="attack_family", columns="social_proof", values="asr_mean")
        .reindex(index=ATTACK_FAMILY_ORDER, columns=UPVOTE_ORDER)
    )
    pivot_sem = (
        summary.pivot(index="attack_family", columns="social_proof", values="asr_sem")
        .reindex(index=ATTACK_FAMILY_ORDER, columns=UPVOTE_ORDER)
    )

    fig, ax = plt.subplots(figsize=(11, 6))
    sns.set_theme(style="whitegrid")

    bar_width = 0.25
    centers = np.arange(len(ATTACK_FAMILY_ORDER))
    for i, sp in enumerate(UPVOTE_ORDER):
        x_pos = centers + (i - 1) * bar_width
        means = pivot_mean[sp].fillna(0).values
        sems = pivot_sem[sp].fillna(0).values
        ax.bar(
            x_pos, means, width=bar_width, yerr=sems, capsize=3,
            label=sp, color=UPVOTE_COLORS[sp],
            edgecolor="black", linewidth=0.4,
            error_kw={"ecolor": "black", "lw": 1},
        )
        for x, m in zip(x_pos, means):
            ax.text(x, m + 1.5, f"{m:.1f}", ha="center", fontsize=8)

    ax.set_xticks(centers)
    ax.set_xticklabels(ATTACK_FAMILY_ORDER)
    ax.set_xlabel("Attack family")
    ax.set_ylabel("ASR (%)")
    ax.set_ylim(0, 100)
    ax.set_title(f"ASR by attack family × social proof {title_suffix}\n(error bars = SEM across domains)")
    ax.legend(title="Social proof", loc="upper right")
    _save(fig, plots_dir / filename)


def plot_per_model_breakdowns(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """For each model: domain×attack heatmap + attack×social-proof bars."""
    per_model_dir = plots_dir / "per_model"
    for model in sorted(df_attack["model_label"].unique()):
        df_m = df_attack[df_attack["model_label"] == model]
        if df_m.empty:
            continue
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_")
        out_dir = per_model_dir / slug
        plot_domain_attack_heatmap(
            df_m, out_dir,
            title_suffix=f"({model})",
            filename="asr_heatmap_domain_x_attack.png",
        )
        plot_attack_family_social_proof(
            df_m, out_dir,
            title_suffix=f"({model})",
            filename="asr_attack_family_x_social_proof.png",
        )


def plot_category_distribution(df_attack: pd.DataFrame, plots_dir: Path) -> None:
    """Stacked bar of Cat1/Cat2/Cat3 per model (over attack rows only)."""
    counts = (
        df_attack.groupby(["model_label", "judge_category"]).size()
        .unstack(fill_value=0)
        .reindex(columns=[1, 2, 3], fill_value=0)
    )
    pct = counts.div(counts.sum(axis=1), axis=0) * 100
    pct = pct.rename(columns={1: "Cat1 (Full)", 2: "Cat2 (Partial)", 3: "Cat3 (Failure)"})

    fig, ax = plt.subplots(figsize=(11, 6))
    pct.plot(kind="bar", stacked=True, ax=ax, color=["#d62728", "#ff7f0e", "#2ca02c"])
    for container in ax.containers:
        ax.bar_label(container, fmt="%.1f%%", label_type="center", fontsize=8, color="white")
    ax.set_title("Judge Category Distribution per Model (attack rows only)")
    ax.set_ylabel("Share of rows (%)")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 100)
    ax.legend(title="Judge category", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, plots_dir / "category_distribution_per_model.png")


# --- ADVANCED LOADING (optional pathway enrichment) ---

def _parse_phase(phase: str) -> Optional[Dict[str, str]]:
    """Parse '<domain>/<bot_group>/<upvote>/<attack>-attack' into key parts."""
    if not isinstance(phase, str):
        return None
    parts = phase.strip().split("/")
    if len(parts) != 4:
        return None
    return {
        "domain": parts[0],
        "bot_group": parts[1],
        "upvote": parts[2],
        "attack": parts[3].replace("-attack", ""),
    }


def load_evaluated_pathways(evaluated_dir: Path) -> Optional[pd.DataFrame]:
    """Optionally load pathway columns from analyze_reasoning_cot.py outputs."""
    if not evaluated_dir.is_dir():
        return None

    frames: List[pd.DataFrame] = []
    for sub in sorted(p for p in evaluated_dir.iterdir() if p.is_dir()):
        for csv_path in sorted(sub.glob("evaluated_*.csv")):
            try:
                df = pd.read_csv(csv_path)
            except Exception as e:
                print(f"  [WARN] could not read {csv_path}: {e}")
                continue
            required = {"phase", "query_id", "judge_pathway"}
            if not required.issubset(df.columns):
                continue
            keys = df["phase"].apply(_parse_phase).dropna()
            if keys.empty:
                continue
            parsed = pd.DataFrame(list(keys.values), index=keys.index)
            df = df.loc[parsed.index].copy()
            df["domain"] = parsed["domain"].values
            df["bot_group"] = parsed["bot_group"].values
            df["upvote"] = parsed["upvote"].values
            df["attack"] = parsed["attack"].values
            df["model_label"] = sub.name
            keep_cols = [
                "model_label", "domain", "bot_group", "upvote", "attack", "query_id",
                "judge_pathway",
            ]
            optional = [
                "judge_hazard_mentioned", "judge_eliminated",
                "judge_fake_authority_mentioned", "judge_authority_justified",
            ]
            keep_cols += [c for c in optional if c in df.columns]
            frames.append(df[keep_cols])

    if not frames:
        return None

    enriched = pd.concat(frames, ignore_index=True)
    enriched = enriched.drop_duplicates(
        subset=["model_label", "domain", "bot_group", "upvote", "attack", "query_id"],
        keep="last",
    )
    return enriched


def attach_pathways(df_all: pd.DataFrame, evaluated_dir: Path) -> pd.DataFrame:
    """Left-merge pathway columns onto df_all if available; otherwise return df_all."""
    enriched = load_evaluated_pathways(evaluated_dir)
    if enriched is None or enriched.empty:
        return df_all
    merged = df_all.merge(
        enriched,
        on=["model_label", "domain", "bot_group", "upvote", "attack", "query_id"],
        how="left",
    )
    n_with_pathway = merged["judge_pathway"].notna().sum()
    print(f"  [PATHWAY] enriched {n_with_pathway}/{len(merged)} rows with judge_pathway")
    return merged


# --- ADVANCED PLOTS ---

def plot_pathway_fingerprint(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Stacked bar of pathway distribution among Cat1 successes per model."""
    if "judge_pathway" not in df_attack.columns:
        print("  [SKIP] pathway fingerprint — judge_pathway not available")
        return
    status_col = "judge_status" if "judge_status" in df_attack.columns else "judge_category"
    cat1 = df_attack[(df_attack[status_col] == 1) & df_attack["judge_pathway"].notna()].copy()
    if cat1.empty:
        print("  [SKIP] pathway fingerprint — no Cat1 rows with pathway")
        return

    cat1["pathway_human"] = cat1["judge_pathway"].map(PATHWAY_HUMAN).fillna("Other")
    counts = (
        cat1.groupby(["model_label", "pathway_human"]).size()
        .unstack(fill_value=0)
        .reindex(columns=PATHWAY_DISPLAY_ORDER, fill_value=0)
    )
    pct = counts.div(counts.sum(axis=1), axis=0) * 100
    pct = pct.loc[pct.sum(axis=1).sort_values(ascending=False).index]

    fig, ax = plt.subplots(figsize=(12, 6.5))
    pct.plot(
        kind="bar", stacked=True, ax=ax,
        color=[PATHWAY_COLORS[c] for c in PATHWAY_DISPLAY_ORDER],
        edgecolor="white", linewidth=0.5,
    )
    for container in ax.containers:
        ax.bar_label(container, fmt="%.0f%%", label_type="center", fontsize=8, color="white")
    ax.set_title(
        "Logic Hijacking Fingerprint per Model\n(distribution of reasoning pathways among Cat1 successes)",
        fontsize=13, fontweight="bold",
    )
    ax.set_ylabel("Share of Cat1 successes (%)", fontsize=11)
    ax.set_xlabel("Model", fontsize=11)
    ax.set_ylim(0, 100)
    ax.legend(title="Pathway", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, advanced_dir / "pathway_fingerprint_per_model.png")


def plot_per_domain_consistency(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Boxplot of per-domain ASR per model (one ASR value per domain)."""
    per_md = (
        df_attack.groupby(["model_label", "domain"])["judge_score"]
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
        order=order, ax=ax,
        palette="Set2", width=0.6, fliersize=4,
    )
    sns.stripplot(
        data=per_md, x="model_label", y="asr",
        order=order, ax=ax, color="black", size=3, alpha=0.6, jitter=0.2,
    )
    ax.set_title(
        "Per-domain ASR distribution per model\n(each point = one of the 10 domains)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Model", fontsize=11)
    ax.set_ylabel("ASR % across domains", fontsize=11)
    ax.set_ylim(0, 100)
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    _save(fig, advanced_dir / "asr_per_domain_consistency.png")


def _radar_axes(ax: plt.Axes, categories: List[str]) -> List[float]:
    """Configure a polar Axes for a radar chart with the given categories."""
    n = len(categories)
    angles = [i / n * 2 * np.pi for i in range(n)]
    angles_closed = angles + [angles[0]]
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles)
    ax.set_xticklabels(categories, fontsize=10)
    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color="gray")
    ax.grid(True, alpha=0.4)
    return angles_closed


def plot_vulnerability_radar(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Combined and per-model radar charts (axes = attack families)."""
    summary = summarize_groups(df_attack, ["model_label", "attack_family"])
    pivot = summary.pivot(index="model_label", columns="attack_family", values="asr_mean")
    pivot = pivot.reindex(columns=ATTACK_FAMILY_ORDER).fillna(0)

    fig, ax = plt.subplots(figsize=(8.5, 8), subplot_kw={"projection": "polar"})
    angles_closed = _radar_axes(ax, ATTACK_FAMILY_ORDER)
    palette = sns.color_palette("Set2", n_colors=len(pivot))
    for color, (model, row) in zip(palette, pivot.iterrows()):
        values = list(row.values) + [row.values[0]]
        ax.plot(angles_closed, values, lw=2, color=color, label=model)
        ax.fill(angles_closed, values, alpha=0.12, color=color)
    ax.set_title("Vulnerability Radar — ASR % by attack family", fontsize=13, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.05), fontsize=9)
    _save(fig, advanced_dir / "vulnerability_radar_combined.png")

    per_model_dir = advanced_dir / "per_model_radar"
    for color_idx, (model, row) in enumerate(pivot.iterrows()):
        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"projection": "polar"})
        angles_closed = _radar_axes(ax, ATTACK_FAMILY_ORDER)
        values = list(row.values) + [row.values[0]]
        c = palette[color_idx]
        ax.plot(angles_closed, values, lw=2.2, color=c)
        ax.fill(angles_closed, values, alpha=0.25, color=c)
        for ang, val, fam in zip(angles_closed[:-1], row.values, ATTACK_FAMILY_ORDER):
            ax.text(ang, val + 5, f"{val:.1f}%", ha="center", fontsize=9, color="black")
        ax.set_title(f"Vulnerability Radar — {model}", fontsize=12, fontweight="bold", pad=18)
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", model).strip("_")
        _save(fig, per_model_dir / f"radar_{slug}.png")


def plot_social_proof_lift(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Bar chart of ASR(High) − ASR(None) per model × attack family."""
    df = df_attack[df_attack["social_proof"].isin(UPVOTE_ORDER)].copy()
    if df.empty:
        return
    summary = summarize_groups(df, ["model_label", "attack_family", "social_proof"])
    pivot = summary.pivot_table(
        index=["model_label", "attack_family"], columns="social_proof", values="asr_mean"
    ).reindex(columns=UPVOTE_ORDER)
    pivot["lift"] = pivot["High"] - pivot["None"]
    lift = pivot["lift"].reset_index()

    models = sorted(lift["model_label"].unique())
    fig, ax = plt.subplots(figsize=(13, 6.5))
    sns.set_theme(style="whitegrid")
    palette = sns.color_palette("Set2", n_colors=len(ATTACK_FAMILY_ORDER))
    bar_width = 0.25
    centers = np.arange(len(models))
    for i, fam in enumerate(ATTACK_FAMILY_ORDER):
        sub = lift[lift["attack_family"] == fam].set_index("model_label").reindex(models)
        x_pos = centers + (i - 1) * bar_width
        vals = sub["lift"].fillna(0).values
        ax.bar(x_pos, vals, width=bar_width, label=fam, color=palette[i],
               edgecolor="black", linewidth=0.4)
        for x, v in zip(x_pos, vals):
            ax.text(x, v + (0.6 if v >= 0 else -2), f"{v:+.1f}", ha="center", fontsize=8)

    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(centers)
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_xlabel("Model", fontsize=11)
    ax.set_ylabel("ΔASR (%) — High minus None", fontsize=11)
    ax.set_title(
        "Social-proof Lift per Model × Attack Family\n(positive = upvotes increase ASR)",
        fontsize=13, fontweight="bold",
    )
    ax.legend(title="Attack family", bbox_to_anchor=(1.02, 1), loc="upper left")
    _save(fig, advanced_dir / "social_proof_lift_per_model_per_attack.png")


def plot_domain_difficulty_ranking(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Bar chart ranking domains hardest → easiest, mean ASR across all models."""
    per_dom = (
        df_attack.groupby("domain_pretty")["judge_score"]
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
    ax.set_xlabel("Mean ASR % across all models", fontsize=11)
    ax.set_ylabel("Domain", fontsize=11)
    ax.set_title("Domain Difficulty Ranking (hardest → easiest to attack)",
                 fontsize=13, fontweight="bold")
    _save(fig, advanced_dir / "domain_difficulty_ranking.png")


def plot_reasoning_specificity_matrix(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Heatmap: injected attack_family (rows) vs detected judge_pathway (cols), row-normalized %.

    Diagonal mass = attacks trigger the intended reasoning mechanism.
    """
    if "judge_pathway" not in df_attack.columns:
        print("  [SKIP] reasoning specificity — judge_pathway not available")
        return
    status_col = "judge_status" if "judge_status" in df_attack.columns else "judge_category"
    cat1 = df_attack[(df_attack[status_col] == 1) & df_attack["judge_pathway"].notna()].copy()
    if cat1.empty:
        print("  [SKIP] reasoning specificity — no Cat1 rows with pathway")
        return

    pathway_cols = ["Logic Hijacking", "Authority Deference", "Attribute Anchoring", "Benign/Other"]
    counts = (
        cat1.groupby(["attack_family", "judge_pathway"]).size()
        .unstack(fill_value=0)
        .reindex(index=ATTACK_FAMILY_ORDER, columns=pathway_cols, fill_value=0)
    )
    row_totals = counts.sum(axis=1).replace(0, np.nan)
    pct = counts.div(row_totals, axis=0).fillna(0) * 100

    expected: Dict[str, str] = {
        "Safety": "Logic Hijacking",
        "Authority": "Authority Deference",
        "Attribute": "Attribute Anchoring",
    }

    fig, ax = plt.subplots(figsize=(11, 5.5))
    sns.heatmap(
        pct, annot=True, fmt=".1f", cmap="viridis",
        vmin=0, vmax=100, ax=ax, cbar_kws={"label": "% of Cat1 successes"},
        linewidths=0.5, linecolor="white",
    )
    for r, family in enumerate(ATTACK_FAMILY_ORDER):
        c = pathway_cols.index(expected[family])
        ax.add_patch(plt.Rectangle((c, r), 1, 1, fill=False, edgecolor="red", lw=2.5))

    ax.set_title(
        "Reasoning Specificity — injected attack vs detected reasoning pathway\n"
        "(rows normalized to 100%; red = expected diagonal)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Detected reasoning pathway", fontsize=11)
    ax.set_ylabel("Injected attack family", fontsize=11)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    _save(fig, advanced_dir / "reasoning_specificity_matrix.png")


def plot_hazard_mention_rate(df_attack: pd.DataFrame, advanced_dir: Path) -> None:
    """Bar chart of hazard mention rate per attack family — unambiguous specificity."""
    if "judge_hazard_mentioned" not in df_attack.columns:
        print("  [SKIP] hazard mention rate — judge_hazard_mentioned not available")
        return
    df = df_attack.dropna(subset=["judge_hazard_mentioned"]).copy()
    if df.empty:
        print("  [SKIP] hazard mention rate — no labeled rows")
        return
    df["judge_hazard_mentioned"] = df["judge_hazard_mentioned"].astype(bool)

    summary = (
        df.groupby("attack_family")["judge_hazard_mentioned"]
        .mean().mul(100).reindex(ATTACK_FAMILY_ORDER).fillna(0)
    )

    fig, ax = plt.subplots(figsize=(8, 5.5))
    palette = sns.color_palette("Set2", n_colors=len(ATTACK_FAMILY_ORDER))
    ax.bar(
        summary.index, summary.values, color=palette,
        edgecolor="black", linewidth=0.5, width=0.6,
    )
    for x, v in enumerate(summary.values):
        ax.text(x, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold")

    ax.set_ylim(0, 100)
    ax.set_ylabel("Hazard-mention rate in CoT (%)", fontsize=11)
    ax.set_xlabel("Attack family", fontsize=11)
    ax.set_title(
        "Hazard Mention Rate per Attack Family\n"
        "(expected: high for Safety, near zero for Authority/Attribute)",
        fontsize=13, fontweight="bold",
    )
    _save(fig, advanced_dir / "hazard_mention_rate_per_attack.png")


# --- TEXT SUMMARY ---

def print_text_summary(df_attack: pd.DataFrame) -> None:
    """Print a compact ASR table per model."""
    summary = summarize_groups(df_attack, ["model_label"])
    summary = summary.sort_values("asr_mean", ascending=False)
    print("\n" + "=" * 60)
    print("ASR (Cat1) per model — overall (mean ± SEM across domains)")
    print("=" * 60)
    for row in summary.itertuples():
        print(f"  {row.model_label:35s}  {row.asr_mean:5.1f}% ± {row.asr_sem:4.1f}%   (n={row.n_domains} domains)")
    print("=" * 60)


# --- CLI ---

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Aggregate per-model judged CSVs and produce model-vs-model plots.",
    )
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR,
                        help="Directory containing per-model subfolders.")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUT_CSV,
                        help="Path for combined judged CSV.")
    parser.add_argument("--plots-dir", type=Path, default=DEFAULT_PLOTS_DIR,
                        help="Directory where plots are written.")
    parser.add_argument("--evaluated-dir", type=Path, default=DEFAULT_EVALUATED_DIR,
                        help="Optional dir with analyze_reasoning_cot.py outputs (for pathway plot).")
    parser.add_argument("--skip-advanced", action="store_true",
                        help="Skip the advanced/ plots block.")
    return parser.parse_args()


def main() -> None:
    """Entry point: aggregate, save CSV, render plots, print summary."""
    args = parse_args()
    print(f"Logs dir: {args.logs_dir}")

    df_all = load_all(args.logs_dir)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(args.output_csv, index=False)
    print(f"\nCombined judged CSV: {args.output_csv}  ({len(df_all)} rows, {df_all['model_label'].nunique()} models)")

    df_attack = df_all[df_all["attack"] != "clean"].copy()
    if df_attack.empty:
        print("[WARN] No attack rows found — plots/summary will be skipped.")
        return

    plot_overall(df_attack, args.plots_dir)
    plot_per_attack(df_attack, args.plots_dir)
    plot_per_upvote(df_attack, args.plots_dir)
    plot_heatmap(df_attack, args.plots_dir)
    plot_category_distribution(df_attack, args.plots_dir)

    plot_domain_attack_heatmap(df_attack, args.plots_dir)
    plot_attack_family_social_proof(df_attack, args.plots_dir)
    plot_per_model_breakdowns(df_attack, args.plots_dir)

    if not args.skip_advanced:
        df_attack_adv = attach_pathways(df_attack, args.evaluated_dir)
        advanced_dir = args.plots_dir / ADVANCED_SUBDIR
        plot_pathway_fingerprint(df_attack_adv, advanced_dir)
        plot_per_domain_consistency(df_attack_adv, advanced_dir)
        plot_vulnerability_radar(df_attack_adv, advanced_dir)
        plot_social_proof_lift(df_attack_adv, advanced_dir)
        plot_domain_difficulty_ranking(df_attack_adv, advanced_dir)
        plot_reasoning_specificity_matrix(df_attack_adv, advanced_dir)
        plot_hazard_mention_rate(df_attack_adv, advanced_dir)

    print_text_summary(df_attack)


if __name__ == "__main__":
    main()
