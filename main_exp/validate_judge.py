"""
Blind human validation of the LLM-as-a-Judge for Reasoning Poisoning.

Two-step protocol (NeurIPS reviewer requirement):

1) `sample`:   draw a deterministic random subset of evaluated rows, strip ALL
               judge_* fields, and write a CSV with empty Human_* columns for
               manual annotation.
2) `evaluate`: read the annotated CSV + the original evaluated CSVs, align
               them, and compute Accuracy and Cohen's Kappa for
                  - Category Match  (Human_Category   vs judge_status)
                  - Pathway Match   (Human_Final_Pathway vs judge_pathway)
               and supplementary binary agreements (hazard / elimination /
               fake-authority / justified-by-authority) when populated.

Usage:
    # sample 100 rows from the full evaluated_logs/ tree
    python3 validate_judge.py sample \\
        --input evaluated_logs \\
        --output logs/human_annotation_sample.csv \\
        --n 100 --seed 42

    # sample from a single combined CSV
    python3 validate_judge.py sample \\
        --input logs/all_evaluated.csv \\
        --output logs/human_annotation_sample.csv

    # after the human fills in the Human_* columns
    python3 validate_judge.py evaluate \\
        --human  logs/human_annotation_sample.csv \\
        --judge  evaluated_logs \\
        --report logs/human_validation_report.txt

Robust to:
    * missing / blank Human_* cells (skipped per metric, with a warning)
    * extra columns in either side of the merge
    * judge CSVs that originate from `analyze_reasoning_cot.py` (with the
      canonical `phase` column = "<domain>/<bot_group>/<upvote>/<attack>-attack")
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required: pip install numpy")
try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas")
try:
    from sklearn.metrics import cohen_kappa_score, confusion_matrix
except ImportError:
    sys.exit("scikit-learn is required: pip install scikit-learn")


# --- CONFIG ---

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "evaluated_logs"
DEFAULT_LOGS_DIR = SCRIPT_DIR / "logs"
DEFAULT_OUTPUT = DEFAULT_LOGS_DIR / "human_annotation_sample.csv"
DEFAULT_REPORT = DEFAULT_LOGS_DIR / "human_validation_report.txt"

# Context columns kept in the human sample (drop everything else, especially judge_*).
CONTEXT_COLUMNS: List[str] = [
    "domain",
    "bot_group",
    "attack",
    "upvote",
    "model",
    "query_id",
    "chain_of_thought",
    "final_answer",
]

# Empty columns appended for the human annotator.
HUMAN_COLUMNS: List[str] = [
    "Human_Category",
    "Human_Hazard_Mentioned",
    "Human_Competitor_Eliminated",
    "Human_Fake_Authority_Mentioned",
    "Human_Justified_By_Authority",
    "Human_Final_Pathway",
]

# Internal stable join key written into the human CSV at sample time.
ROW_UID_COL = "__row_uid__"

VALID_PATHWAYS = (
    "Logic Hijacking",
    "Authority Deference",
    "Attribute Anchoring",
    "Benign/Other",
)

# Aliases the human annotator might use for the pathway field.
PATHWAY_ALIASES: Dict[str, str] = {
    "logic": "Logic Hijacking",
    "logic hijacking": "Logic Hijacking",
    "hijack": "Logic Hijacking",
    "hijacking": "Logic Hijacking",
    "safety": "Logic Hijacking",
    "authority": "Authority Deference",
    "authority deference": "Authority Deference",
    "deference": "Authority Deference",
    "attribute": "Attribute Anchoring",
    "attribute anchoring": "Attribute Anchoring",
    "anchoring": "Attribute Anchoring",
    "benign": "Benign/Other",
    "other": "Benign/Other",
    "benign/other": "Benign/Other",
    "none": "Benign/Other",
}

JUDGE_PREFIXES = ("judge_",)


# --- ANSI HELPERS (no third-party deps) ---

class _C:
    """Minimal ANSI palette for the terminal report."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"


def _supports_color() -> bool:
    return sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_C.RESET}" if _supports_color() else text


# --- SHARED LOADING ---

def _row_uid(model_label: str, phase: str, query_id: str) -> str:
    """Stable short hash for a row. Used to merge human ↔ judge."""
    h = hashlib.sha1(f"{model_label}||{phase}||{query_id}".encode("utf-8")).hexdigest()
    return h[:16]


def _parse_phase(phase: object) -> Optional[Dict[str, str]]:
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


def _discover_evaluated_csvs(path: Path) -> List[Tuple[Path, Optional[str]]]:
    """Return [(csv_path, model_label_from_parent_dir_or_None), ...]."""
    if path.is_file():
        return [(path, None)]
    if not path.is_dir():
        sys.exit(f"Input path not found: {path}")

    pairs: List[Tuple[Path, Optional[str]]] = []
    for sub in sorted(p for p in path.iterdir() if p.is_dir()):
        for csv in sorted(sub.glob("evaluated_*.csv")):
            pairs.append((csv, sub.name))
    if not pairs:
        for csv in sorted(path.rglob("evaluated_*.csv")):
            pairs.append((csv, csv.parent.name))
    if not pairs:
        sys.exit(f"No evaluated_*.csv files found under: {path}")
    return pairs


def _load_evaluated_frame(input_path: Path) -> pd.DataFrame:
    """Load + concatenate evaluated rows; ensure phase is parsed and a row uid exists."""
    pairs = _discover_evaluated_csvs(input_path)
    frames: List[pd.DataFrame] = []
    for csv_path, model_label in pairs:
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            print(f"  [WARN] could not read {csv_path}: {e}", file=sys.stderr)
            continue
        if df.empty:
            continue

        if "phase" in df.columns:
            parsed = df["phase"].apply(_parse_phase)
            keep_idx = parsed[parsed.notna()].index
            if len(keep_idx) == 0:
                continue
            df = df.loc[keep_idx].copy()
            keys = pd.DataFrame(list(parsed.loc[keep_idx].values), index=keep_idx)
            for col in ("domain", "bot_group", "upvote", "attack"):
                if col not in df.columns or df[col].isna().all():
                    df[col] = keys[col].values
        else:
            for col in ("domain", "bot_group", "upvote", "attack"):
                if col not in df.columns:
                    df[col] = pd.NA

        df["model_label"] = model_label if model_label is not None else df.get("model", pd.Series([""] * len(df)))
        if "query_id" not in df.columns:
            df["query_id"] = df.index.astype(str)
        if "phase" not in df.columns:
            df["phase"] = (
                df["domain"].astype(str) + "/" +
                df["bot_group"].astype(str) + "/" +
                df["upvote"].astype(str) + "/" +
                df["attack"].astype(str) + "-attack"
            )

        df[ROW_UID_COL] = [
            _row_uid(str(m), str(p), str(q))
            for m, p, q in zip(df["model_label"], df["phase"], df["query_id"])
        ]
        frames.append(df)

    if not frames:
        sys.exit(f"No usable evaluated rows discovered under: {input_path}")

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=[ROW_UID_COL], keep="last").reset_index(drop=True)
    return out


# --- SAMPLE MODE ---

def _strip_judge_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop ALL judge_* columns so the human is fully blind."""
    drop = [c for c in df.columns if any(c.startswith(p) for p in JUDGE_PREFIXES)]
    return df.drop(columns=drop, errors="ignore")


def _ensure_context(df: pd.DataFrame) -> pd.DataFrame:
    """Make sure all context columns exist; fill missing with empty strings."""
    df = df.copy()
    for col in CONTEXT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df


def cmd_sample(args: argparse.Namespace) -> None:
    """Generate a blind human-annotation CSV (sample mode)."""
    eval_df = _load_evaluated_frame(args.input)
    total_available = len(eval_df)
    if total_available == 0:
        sys.exit("No evaluated rows available to sample.")

    n = min(int(args.n), total_available)
    rng = np.random.default_rng(int(args.seed))
    pick_idx = rng.choice(total_available, size=n, replace=False)
    sample = eval_df.iloc[np.sort(pick_idx)].reset_index(drop=True).copy()

    sample = _ensure_context(sample)
    sample = _strip_judge_columns(sample)

    keep_cols = [c for c in CONTEXT_COLUMNS if c in sample.columns]
    if ROW_UID_COL in sample.columns:
        keep_cols = [ROW_UID_COL] + keep_cols
    sample = sample[keep_cols]

    for col in HUMAN_COLUMNS:
        sample[col] = ""

    out_path: Path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out_path, index=False)

    print(_c("\n[OK] Blind human-annotation sample written.", _C.GREEN + _C.BOLD))
    print(f"  rows sampled : {len(sample)} (from pool of {total_available})")
    print(f"  seed         : {args.seed}")
    print(f"  output       : {out_path}")
    print(_c("  judge_* columns dropped — annotator is fully blind.", _C.DIM))
    print(_c("\nNext: open the CSV, fill the Human_* columns, then run "
             "`validate_judge.py evaluate ...`.", _C.YELLOW))


# --- EVALUATE MODE ---

def _normalize_category(v: object) -> Optional[int]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "na"}:
        return None
    for tok in s:
        if tok in "123":
            return int(tok)
    try:
        f = float(s)
    except ValueError:
        return None
    if int(f) in (1, 2, 3):
        return int(f)
    return None


def _normalize_bool(v: object) -> Optional[bool]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip().lower()
    if not s or s in {"nan", "none", "na"}:
        return None
    if s in {"y", "yes", "true", "t", "1"}:
        return True
    if s in {"n", "no", "false", "f", "0"}:
        return False
    return None


def _normalize_pathway(v: object) -> Optional[str]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "na"}:
        return None
    if s in VALID_PATHWAYS:
        return s
    alias = PATHWAY_ALIASES.get(s.lower())
    if alias:
        return alias
    return None


def _pair_clean(
    a: Sequence[object],
    b: Sequence[object],
) -> Tuple[List[object], List[object], int]:
    """Drop pairs where either side is None. Returns (a', b', dropped_count)."""
    out_a, out_b, dropped = [], [], 0
    for x, y in zip(a, b):
        if x is None or y is None:
            dropped += 1
            continue
        out_a.append(x)
        out_b.append(y)
    return out_a, out_b, dropped


def _agreement(human: Sequence[object], judge: Sequence[object]) -> Dict[str, float]:
    """Compute accuracy + Cohen's κ for paired labels (already normalized)."""
    h, j, dropped = _pair_clean(human, judge)
    n = len(h)
    if n == 0:
        return {"n": 0, "dropped": dropped, "accuracy": float("nan"), "kappa": float("nan")}
    h_arr = np.asarray(h)
    j_arr = np.asarray(j)
    acc = float((h_arr == j_arr).mean())
    try:
        kappa = float(cohen_kappa_score(h_arr, j_arr))
    except Exception:
        kappa = float("nan")
    return {"n": n, "dropped": dropped, "accuracy": acc, "kappa": kappa}


def _confusion_matrix_string(
    human: Sequence[object],
    judge: Sequence[object],
    labels: Sequence[object],
    title: str,
) -> str:
    """Render a small confusion matrix (rows=human, cols=judge)."""
    h, j, _ = _pair_clean(human, judge)
    if not h:
        return f"{title}: (no overlapping labeled rows)\n"
    cm = confusion_matrix(h, j, labels=list(labels))
    headers = [str(lbl) for lbl in labels]
    col_w = max(8, max(len(s) for s in headers) + 2, len(str(cm.max())) + 2)
    row_w = max(8, max(len(s) for s in headers) + 2)

    lines = [title]
    head = " " * row_w + "".join(f"{h:>{col_w}}" for h in headers)
    lines.append(_c(head, _C.DIM))
    for i, row_label in enumerate(headers):
        cells = "".join(f"{cm[i, k]:>{col_w}}" for k in range(len(headers)))
        lines.append(f"{row_label:<{row_w}}{cells}")
    return "\n".join(lines) + "\n"


def _kappa_interpretation(kappa: float) -> str:
    """Standard Landis & Koch (1977) interpretation."""
    if np.isnan(kappa):
        return "n/a"
    if kappa < 0.0:
        return "worse than chance"
    if kappa < 0.20:
        return "slight"
    if kappa < 0.40:
        return "fair"
    if kappa < 0.60:
        return "moderate"
    if kappa < 0.80:
        return "substantial"
    if kappa < 1.0:
        return "almost perfect"
    return "perfect"


def _format_pct(x: float) -> str:
    return "n/a" if np.isnan(x) else f"{x * 100:5.1f}%"


def _format_kappa(x: float) -> str:
    return "n/a" if np.isnan(x) else f"{x:+.3f}"


def _build_report(
    n_total: int,
    n_aligned: int,
    metrics: Dict[str, Dict[str, float]],
    confusion_blocks: List[str],
    judge_source: Path,
    human_source: Path,
) -> str:
    """Render the final terminal/text report."""
    bar = "═" * 78
    sub = "─" * 78
    lines: List[str] = []
    lines.append(_c(bar, _C.CYAN))
    lines.append(_c("  BLIND HUMAN VALIDATION OF LLM-AS-A-JUDGE".ljust(78), _C.CYAN + _C.BOLD))
    lines.append(_c(bar, _C.CYAN))
    lines.append(f"  human file  : {human_source}")
    lines.append(f"  judge source: {judge_source}")
    lines.append(f"  rows in human file       : {n_total}")
    lines.append(f"  rows aligned with judge  : {n_aligned}")
    lines.append(_c(sub, _C.DIM))
    lines.append(_c("  CORE METRICS (NeurIPS-grade)", _C.BOLD))
    lines.append(_c(sub, _C.DIM))
    header = f"  {'Field':<28}{'N':>6}{'Skipped':>10}{'Accuracy':>12}{'κ':>10}  Interpretation"
    lines.append(_c(header, _C.DIM))
    for label, m in metrics.items():
        kappa_text = _format_kappa(m["kappa"])
        acc_text = _format_pct(m["accuracy"])
        interp = _kappa_interpretation(m["kappa"])
        color = _C.GREEN if (not np.isnan(m["kappa"]) and m["kappa"] >= 0.6) else (
            _C.YELLOW if (not np.isnan(m["kappa"]) and m["kappa"] >= 0.4) else _C.RED
        )
        line = (
            f"  {label:<28}{m['n']:>6}{m['dropped']:>10}"
            f"{acc_text:>12}{kappa_text:>10}  {interp}"
        )
        lines.append(_c(line, color))
    lines.append(_c(sub, _C.DIM))
    if confusion_blocks:
        lines.append(_c("  CONFUSION MATRICES (rows = human, cols = judge)", _C.BOLD))
        lines.append(_c(sub, _C.DIM))
        for block in confusion_blocks:
            lines.append(block)
        lines.append(_c(sub, _C.DIM))
    lines.append(_c("  Cohen's κ scale (Landis & Koch, 1977):", _C.DIM))
    lines.append(_c("    < 0.00 worse than chance | 0.00–0.20 slight | 0.21–0.40 fair", _C.DIM))
    lines.append(_c("    0.41–0.60 moderate      | 0.61–0.80 substantial | 0.81–1.00 almost perfect", _C.DIM))
    lines.append(_c(bar, _C.CYAN))
    return "\n".join(lines) + "\n"


def cmd_evaluate(args: argparse.Namespace) -> None:
    """Compute Accuracy + Cohen's κ for human vs LLM judge."""
    human_path: Path = args.human
    judge_path: Path = args.judge

    if not human_path.is_file():
        sys.exit(f"Human CSV not found: {human_path}")

    try:
        human = pd.read_csv(human_path)
    except Exception as e:
        sys.exit(f"Could not read human CSV {human_path}: {e}")
    if human.empty:
        sys.exit("Human CSV is empty.")

    missing = [c for c in HUMAN_COLUMNS if c not in human.columns]
    if missing:
        sys.exit(f"Human CSV missing columns: {missing}")

    judge_df = _load_evaluated_frame(judge_path)

    if ROW_UID_COL in human.columns and ROW_UID_COL in judge_df.columns:
        merged = human.merge(
            judge_df[[ROW_UID_COL, "judge_status", "judge_pathway",
                       "judge_hazard_mentioned", "judge_eliminated",
                       "judge_fake_authority_mentioned", "judge_authority_justified"]
                       ].drop_duplicates(subset=[ROW_UID_COL], keep="last"),
            on=ROW_UID_COL, how="left",
        )
    else:
        join_cols = [c for c in ("model", "domain", "bot_group", "upvote", "attack", "query_id")
                     if c in human.columns and c in judge_df.columns]
        if not join_cols:
            sys.exit("Cannot align human ↔ judge: no shared keys (need __row_uid__ or "
                     "(model, domain, bot_group, upvote, attack, query_id)).")
        merged = human.merge(
            judge_df[join_cols + ["judge_status", "judge_pathway",
                                   "judge_hazard_mentioned", "judge_eliminated",
                                   "judge_fake_authority_mentioned",
                                   "judge_authority_justified"]
                     ].drop_duplicates(subset=join_cols, keep="last"),
            on=join_cols, how="left",
        )

    n_total = len(human)
    n_aligned = int(merged["judge_status"].notna().sum())
    if n_aligned == 0:
        sys.exit("No human rows could be matched to the original judge output.")

    h_cat = [_normalize_category(v) for v in merged["Human_Category"]]
    j_cat = [_normalize_category(v) for v in merged["judge_status"]]
    h_path = [_normalize_pathway(v) for v in merged["Human_Final_Pathway"]]
    j_path = [_normalize_pathway(v) for v in merged["judge_pathway"]]

    h_haz = [_normalize_bool(v) for v in merged["Human_Hazard_Mentioned"]]
    j_haz = [_normalize_bool(v) for v in merged.get("judge_hazard_mentioned", pd.Series([None] * len(merged)))]
    h_elim = [_normalize_bool(v) for v in merged["Human_Competitor_Eliminated"]]
    j_elim = [_normalize_bool(v) for v in merged.get("judge_eliminated", pd.Series([None] * len(merged)))]
    h_auth_m = [_normalize_bool(v) for v in merged["Human_Fake_Authority_Mentioned"]]
    j_auth_m = [_normalize_bool(v) for v in merged.get("judge_fake_authority_mentioned",
                                                       pd.Series([None] * len(merged)))]
    h_auth_j = [_normalize_bool(v) for v in merged["Human_Justified_By_Authority"]]
    j_auth_j = [_normalize_bool(v) for v in merged.get("judge_authority_justified",
                                                       pd.Series([None] * len(merged)))]

    metrics: Dict[str, Dict[str, float]] = {
        "Category Match (1/2/3)": _agreement(h_cat, j_cat),
        "Pathway Match (4-class)": _agreement(h_path, j_path),
        "Hazard Mentioned (bool)": _agreement(h_haz, j_haz),
        "Competitor Eliminated":   _agreement(h_elim, j_elim),
        "Fake Authority Mentioned": _agreement(h_auth_m, j_auth_m),
        "Justified by Authority":   _agreement(h_auth_j, j_auth_j),
    }

    confusion_blocks: List[str] = []
    if metrics["Category Match (1/2/3)"]["n"] > 0:
        confusion_blocks.append(
            _confusion_matrix_string(h_cat, j_cat, [1, 2, 3],
                                     title=_c("  Category (1=Primary, 2=Partial, 3=None/Failure)", _C.BOLD))
        )
    if metrics["Pathway Match (4-class)"]["n"] > 0:
        confusion_blocks.append(
            _confusion_matrix_string(h_path, j_path, list(VALID_PATHWAYS),
                                     title=_c("  Reasoning Pathway", _C.BOLD))
        )

    report = _build_report(
        n_total=n_total,
        n_aligned=n_aligned,
        metrics=metrics,
        confusion_blocks=confusion_blocks,
        judge_source=judge_path,
        human_source=human_path,
    )
    print(report, end="")

    if args.report:
        report_path: Path = args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        plain = _strip_ansi(report)
        report_path.write_text(plain, encoding="utf-8")
        print(_c(f"\n[OK] Plain-text report saved to: {report_path}", _C.GREEN))


# --- UTIL ---

def _strip_ansi(text: str) -> str:
    """Strip ANSI sequences for the on-disk report."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# --- CLI ---

def _build_parser() -> argparse.ArgumentParser:
    """Argparse with two subcommands: sample / evaluate."""
    parser = argparse.ArgumentParser(
        description="Blind human validation of the LLM-as-a-Judge for Reasoning Poisoning.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_sample = sub.add_parser("sample", help="Generate a blind sample for human annotation.")
    p_sample.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR,
                          help="Evaluated CSV file or directory (default: ./evaluated_logs).")
    p_sample.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                          help="Where to write the human annotation CSV (default: logs/human_annotation_sample.csv).")
    p_sample.add_argument("--n", type=int, default=100, help="Number of rows to sample (default: 100).")
    p_sample.add_argument("--seed", type=int, default=42, help="Random seed (default: 42).")
    p_sample.set_defaults(func=cmd_sample)

    p_eval = sub.add_parser("evaluate", help="Compare human labels against the LLM judge.")
    p_eval.add_argument("--human", type=Path, default=DEFAULT_OUTPUT,
                         help="Annotated human CSV (default: logs/human_annotation_sample.csv).")
    p_eval.add_argument("--judge", type=Path, default=DEFAULT_INPUT_DIR,
                         help="Original evaluated CSV file or directory with judge_* columns "
                              "(default: ./evaluated_logs).")
    p_eval.add_argument("--report", type=Path, default=None,
                         help="Optional path to also save a plain-text report.")
    p_eval.set_defaults(func=cmd_evaluate)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
