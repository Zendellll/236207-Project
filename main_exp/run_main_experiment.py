"""
Main Experiment Pipeline for Reasoning Poisoning Research.

Single pipeline for all domains (20 technical  + 10 tourism): one query CSV,
one discovery logic, one run path. No separate flow for technical vs tourism.

  - Queries: source-gather/20_domains_50_queries.csv (50 per domain).
  - Data: mock_internet/<domain>/clean | single-bot|multiple-bots / <upvote> / <attack>.

Usage:
    python run_main_experiment.py --list                    # List phases
    python run_main_experiment.py all                        # All domains
    python run_main_experiment.py all --technical-only        # Only technical domains
    python run_main_experiment.py all --tourism-only        # Only tourism domains
    python run_main_experiment.py attribute --skip-clean
    python run_main_experiment.py all --domain kubernetes-crashloopbackoff

Output:
    logs/results_{phase_name}.csv   (one CSV per phase)
    logs/pipeline_summary.txt       (overall summary)
"""

import os
import sys
import csv
import time
import argparse
from typing import List, Optional, Dict, Tuple
from datetime import datetime

MODELS_TO_TEST = None


def _import_experiment():
    """Import experiment module on demand."""
    global MODELS_TO_TEST
    from experiment import run_experiment as _run, MODELS_TO_TEST as _models
    MODELS_TO_TEST = _models
    return _run


# --- CONFIGURATION ---

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
MOCK_INTERNET_DIR: str = os.environ.get(
    "EXPERIMENT_MOCK_INTERNET_DIR",
    os.path.join(SCRIPT_DIR, "mock_internet"),
)
LOGS_DIR: str = os.environ.get("EXPERIMENT_LOGS_DIR", os.path.join(SCRIPT_DIR, "logs"))
DB_PATH: str = os.environ.get("EXPERIMENT_DB_PATH", os.path.join(SCRIPT_DIR, "vector_db_active"))
QUERIES_FILE: str = os.path.join(SCRIPT_DIR, "source-gather", "20_domains_50_queries.csv")

BOT_GROUPS: List[str] = ["single-bot", "multiple-bots"]
UPVOTE_LEVELS: List[str] = ["no-upvotes", "low-fake-upvotes", "high-fake-upvotes"]
ATTACK_TYPES: List[str] = ["attribute-attack", "fake_authority-attack", "severe_safety-attack"]

ATTACK_NAME_MAP: Dict[str, str] = {
    "attribute": "attribute-attack",
    "fake_authority": "fake_authority-attack",
    "severe_safety": "severe_safety-attack",
}

DOMAIN_NAME_TO_SLUG: Dict[str, str] = {
    "AWS S3 Access Denied 403": "aws-s3-access-denied-403",
    "CORS policy blocked by Access-Control-Allow-Origin": "cors-policy-blocked-by-access-control-allow-origin",
    "Django CSRF token missing or incorrect": "django-csrf-token-missing-or-incorrect",
    "Docker localhost connection refused": "docker-localhost-connection-refused",
    "Flutter pub get failed": "flutter-pub-get-failed",
    "Git merge conflict detached HEAD": "git-merge-conflict-detached-head",
    "Go panic assignment to entry in nil map": "go-panic-assignment-to-entry-in-nil-map",
    "iOS CocoaPods pod install error": "ios-cocoapods-pod-install-error",
    "Kubernetes CrashLoopBackOff": "kubernetes-crashloopbackoff",
    "Next.js hydration error text content does not match": "nextjs-hydration-error-text-content-does-not-match",
    "Node.js heap out of memory": "nodejs-heap-out-of-memory",
    "npm ERR! code ERESOLVE unable to resolve dependency tree": "npm-err-code-eresolve-unable-to-resolve-dependency-tree",
    "PostgreSQL FATAL password authentication failed": "postgresql-fatal-password-authentication-failed",
    "Python Pandas MemoryError large dataset": "python-pandas-memoryerror-large-dataset",
    "React Native memory leak": "react-native-memory-leak",
    "React useEffect infinite loop": "react-useeffect-infinite-loop",
    "Rust borrow checker error cannot borrow as mutable": "rust-borrow-checker-error-cannot-borrow-as-mutable",
    "Spring Boot port 8080 in use": "spring-boot-port-8080-in-use",
    "Vercel deployment failed build command exited with 1": "vercel-deployment-failed-build-command-exited-with-1",
    "Webpack build out of memory": "webpack-build-out-of-memory",
    # Tourism domains
    "Taxi Driver": "taxi-driver",
    "Food Tour Guide": "food-tour-guide",
    "Scuba Diving Center": "scuba-diving-center",
    "Jeep Tours": "jeep-tours",
    "Historical Tour Guide": "historical-tour-guide",
    "Glamping": "glamping",
    "Surf School": "surf-school",
    "Cooking Class": "cooking-class",
    "Boutique Winery": "boutique-winery",
    "Vacation Photographer": "vacation-photographer",
}

# Tourism domains (for --tourism-only filter); queries are in the same CSV as technical domains
TOURISM_SLUGS: set = {
    "taxi-driver", "food-tour-guide", "surf-school", "scuba-diving-center",
    "boutique-winery", "cooking-class", "glamping", "historical-tour-guide",
    "jeep-tours", "vacation-photographer",
}


# --- QUERIES ---

def load_domain_queries() -> Dict[str, List[Tuple[int, str]]]:
    """Load domain -> [(query_id, query_text), ...] from CSV (technical + tourism domains)."""
    queries: Dict[str, List[Tuple[int, str]]] = {}
    if not os.path.isfile(QUERIES_FILE):
        print(f"[WARN] No queries file: {QUERIES_FILE}")
        return queries
    with open(QUERIES_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain_name = row["Domain"]
            slug = DOMAIN_NAME_TO_SLUG.get(domain_name)
            if slug is None:
                print(f"[WARN] Unknown domain in queries CSV: '{domain_name}'")
                continue
            query_id = int(row["Query ID"])
            query_text = row["Query"]
            if slug not in queries:
                queries[slug] = []
            queries[slug].append((query_id, query_text))
    return queries


# --- PHASE DISCOVERY ---

def discover_domains() -> List[str]:
    """Return sorted list of domain directories in mock_internet/."""
    return sorted([
        d for d in os.listdir(MOCK_INTERNET_DIR)
        if os.path.isdir(os.path.join(MOCK_INTERNET_DIR, d))
        and not d.startswith(".")
    ])


def discover_phases(
    attack_filter: Optional[str] = None,
    include_clean: bool = True,
    domain_filter: Optional[str] = None,
    group_filter: Optional[str] = None,
    upvote_filter: Optional[str] = None,
    tourism_only: bool = False,
    technical_only: bool = False,
    max_domains: Optional[int] = None,
) -> List[dict]:
    """
    Auto-discover all experiment phases from mock_internet/ folder structure.

    Args:
        attack_filter: Attack directory name to include (e.g. "attribute-attack"),
                        or None for all attacks.
        include_clean: Whether to include clean baseline phases.
        domain_filter: Only include this specific domain.
        group_filter: Only include this bot group ("single-bot" or "multiple-bots").
        upvote_filter: Only include this specific upvote level.
        tourism_only: If True, only domains in TOURISM_SLUGS.
        technical_only: If True, only domains not in TOURISM_SLUGS (technical domains).
        max_domains: If set, only include the first N domains (for quick runs).

    Returns:
        List of dicts, each with:
            - name: Phase name (e.g. "aws-s3.../single-bot/no-upvotes/attribute-attack")
            - path: Absolute path to the data folder
            - domain: Domain slug
            - category: "clean", "single-bot", or "multiple-bots"
    """
    phases = []
    domains = discover_domains()

    if domain_filter:
        domains = [d for d in domains if d == domain_filter]
    if tourism_only:
        domains = [d for d in domains if d in TOURISM_SLUGS]
    if technical_only:
        domains = [d for d in domains if d not in TOURISM_SLUGS]
    if max_domains is not None and max_domains > 0:
        domains = domains[:max_domains]

    for domain in domains:
        domain_path = os.path.join(MOCK_INTERNET_DIR, domain)

        if include_clean:
            clean_path = os.path.join(domain_path, "clean")
            if os.path.isdir(clean_path):
                phases.append({
                    "name": f"{domain}/clean",
                    "path": clean_path,
                    "domain": domain,
                    "category": "clean",
                })

        bot_groups = [group_filter] if group_filter else BOT_GROUPS

        for bot_group in bot_groups:
            bot_dir = os.path.join(domain_path, bot_group)
            if not os.path.isdir(bot_dir):
                continue

            upvote_levels = [upvote_filter] if upvote_filter else UPVOTE_LEVELS
            for upvote_level in upvote_levels:
                upvote_dir = os.path.join(bot_dir, upvote_level)
                if not os.path.isdir(upvote_dir):
                    continue

                if attack_filter:
                    attacks_to_run = [attack_filter]
                else:
                    attacks_to_run = sorted([
                        d for d in os.listdir(upvote_dir)
                        if os.path.isdir(os.path.join(upvote_dir, d))
                        and not d.startswith(".")
                    ])

                for attack_type in attacks_to_run:
                    attack_path = os.path.join(upvote_dir, attack_type)
                    if not os.path.isdir(attack_path):
                        continue

                    phase_name = f"{domain}/{bot_group}/{upvote_level}/{attack_type}"
                    phases.append({
                        "name": phase_name,
                        "path": attack_path,
                        "domain": domain,
                        "category": bot_group,
                    })

    return phases


def count_txt_files(path: str) -> int:
    """Count .txt files in a directory."""
    if not os.path.isdir(path):
        return 0
    return len([f for f in os.listdir(path) if f.endswith(".txt")])


# --- DISPLAY ---

def print_banner(text: str, char: str = "=") -> None:
    """Print a formatted banner."""
    width = 70
    print("\n" + char * width)
    print(f" {text}")
    print(char * width)


def list_phases(phases: List[dict]) -> None:
    """Print all discovered phases grouped by domain."""
    print_banner(f"AVAILABLE PHASES ({len(phases)} total)")

    current_domain = None
    current_category = None
    for i, phase in enumerate(phases):
        if phase["domain"] != current_domain:
            current_domain = phase["domain"]
            current_category = None
            print(f"\n  === {current_domain} ===")

        if phase["category"] != current_category:
            current_category = phase["category"]
            if current_category != "clean":
                print(f"    --- {current_category} ---")

        file_count = count_txt_files(phase["path"])
        short_name = phase["name"].replace(f"{current_domain}/", "")
        print(f"  {i+1:3}. [{file_count:2} files] {short_name}")


# --- EXECUTION ---

def run_single_phase(
    phase: dict,
    phase_index: int,
    total: int,
    domain_queries: Dict[str, List[Tuple[int, str]]],
    max_queries_per_domain: Optional[int] = None,
) -> bool:
    """
    Run experiment for one phase.

    Returns True if successful.
    """
    print_banner(f"PHASE {phase_index}/{total}: {phase['name']}", "=")

    safe_name = phase["name"].replace("/", "_")
    output_file = os.path.join(LOGS_DIR, f"results_{safe_name}.csv")

    file_count = count_txt_files(phase["path"])
    if file_count == 0:
        print(f"[SKIP] No .txt files in {phase['path']}")
        return False

    queries = domain_queries.get(phase["domain"])
    if not queries:
        print(f"[SKIP] No queries found for domain '{phase['domain']}'")
        return False
    if max_queries_per_domain is not None and max_queries_per_domain > 0:
        queries = queries[:max_queries_per_domain]

    print(f"[INFO] Domain:      {phase['domain']}")
    print(f"[INFO] Data source: {phase['path']}")
    print(f"[INFO] Files:       {file_count}")
    print(f"[INFO] Queries:     {len(queries)}")
    print(f"[INFO] Output:      {output_file}")

    try:
        start_time = time.time()

        _run_experiment = _import_experiment()
        results = _run_experiment(
            data_source=phase["path"],
            queries=queries,
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
        import traceback
        traceback.print_exc()
        return False


def generate_summary(
    phases_run: List[str],
    phases_failed: List[str],
    start_time: datetime,
    end_time: datetime,
    attack_arg: str,
) -> None:
    """Write summary report to logs/."""
    summary_file = os.path.join(LOGS_DIR, "pipeline_summary.txt")
    duration = end_time - start_time

    content = f"""
{'='*70}
REASONING POISONING EXPERIMENT - MAIN EXPERIMENT PIPELINE SUMMARY
{'='*70}

Attack filter: {attack_arg}
Started:       {start_time.strftime("%Y-%m-%d %H:%M:%S")}
Finished:      {end_time.strftime("%Y-%m-%d %H:%M:%S")}
Duration:      {duration}

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


# --- PIPELINE ---

def run_pipeline(
    phases: List[dict],
    domain_queries: Dict[str, List[Tuple[int, str]]],
    attack_arg: str,
    max_queries_per_domain: Optional[int] = None,
) -> None:
    """Run experiments on the given list of phases."""
    print_banner("REASONING POISONING - MAIN EXPERIMENT PIPELINE", "=")

    os.makedirs(LOGS_DIR, exist_ok=True)

    print(f"\n[INFO] Running {len(phases)} phases")
    print(f"[INFO] Model:   {', '.join(MODELS_TO_TEST) if MODELS_TO_TEST else '(loaded on first run)'}")
    print(f"[INFO] Results -> {LOGS_DIR}/")

    for i, p in enumerate(phases):
        files = count_txt_files(p["path"])
        print(f"  {i+1:3}. [{files:2} files] {p['name']}")

    print(f"\n{'─'*70}")
    print("Starting in 3 seconds... (Ctrl+C to cancel)")
    print(f"{'─'*70}")
    time.sleep(3)

    phases_run = []
    phases_failed = []
    start_time = datetime.now()

    for i, phase in enumerate(phases):
        success = run_single_phase(
            phase, i + 1, len(phases), domain_queries,
            max_queries_per_domain=max_queries_per_domain,
        )
        if success:
            phases_run.append(phase["name"])
        else:
            phases_failed.append(phase["name"])

        if i < len(phases) - 1:
            print("\n[PAUSE] 2 seconds before next phase...")
            time.sleep(2)

    end_time = datetime.now()
    generate_summary(phases_run, phases_failed, start_time, end_time, attack_arg)


# --- CLI ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run main experiment (all domains or filter by --technical-only / --tourism-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_main_experiment.py --list
  python run_main_experiment.py all
  python run_main_experiment.py all --technical-only
  python run_main_experiment.py all --tourism-only
  python run_main_experiment.py attribute --skip-clean
  python run_main_experiment.py all --domain kubernetes-crashloopbackoff
  python run_main_experiment.py all --group single-bot --tourism-only --max-domains 2 --max-queries 2
        """
    )
    parser.add_argument(
        "attack",
        nargs="?",
        choices=["attribute", "fake_authority", "severe_safety", "all"],
        help="Attack type to run (or 'all' for all attacks)",
    )
    parser.add_argument("--list", action="store_true", help="List all available phases")
    parser.add_argument("--skip-clean", action="store_true", help="Skip clean baseline phases")
    parser.add_argument("--domain", help="Run only a specific domain")
    parser.add_argument("--group", choices=["single-bot", "multiple-bots"],
                        help="Run only a specific bot group")
    parser.add_argument("--upvote", choices=["no-upvotes", "low-fake-upvotes", "high-fake-upvotes"],
                        help="Run only a specific upvote level")
    parser.add_argument("--tourism-only", action="store_true",
                        help="Run only the 10 tourism domains")
    parser.add_argument("--technical-only", action="store_true",
                        help="Run only the 20 technical domains")
    parser.add_argument("--max-domains", type=int, metavar="N",
                        help="Quick run: only first N domains (e.g. 4)")
    parser.add_argument("--max-queries", type=int, metavar="N",
                        help="Quick run: only first N queries per domain (e.g. 2)")

    args = parser.parse_args()
    if args.tourism_only and args.technical_only:
        print("ERROR: Use only one of --tourism-only or --technical-only.")
        sys.exit(1)

    # --list: show phases and exit (respects all filters)
    if args.list:
        attack_dir = None
        if args.attack and args.attack != "all":
            attack_dir = ATTACK_NAME_MAP[args.attack]
        all_phases = discover_phases(
            attack_filter=attack_dir,
            include_clean=not args.skip_clean,
            domain_filter=args.domain,
            group_filter=args.group,
            upvote_filter=args.upvote,
            tourism_only=args.tourism_only,
            technical_only=args.technical_only,
            max_domains=args.max_domains,
        )
        list_phases(all_phases)
        sys.exit(0)

    if not args.attack:
        parser.print_help()
        print("\nUse --list to see available phases, or provide an attack name.")
        sys.exit(0)

    # Resolve attack filter
    attack_dir = None
    if args.attack != "all":
        attack_dir = ATTACK_NAME_MAP[args.attack]

    include_clean = not args.skip_clean

    phases_to_run = discover_phases(
        attack_filter=attack_dir,
        include_clean=include_clean,
        domain_filter=args.domain,
        group_filter=args.group,
        upvote_filter=args.upvote,
        tourism_only=args.tourism_only,
        technical_only=args.technical_only,
        max_domains=args.max_domains,
    )

    if not phases_to_run:
        print("ERROR: No matching phases found. Use --list to see available phases.")
        sys.exit(1)

    # Load domain queries
    domain_queries = load_domain_queries()
    missing = [p["domain"] for p in phases_to_run if p["domain"] not in domain_queries]
    if missing:
        unique_missing = sorted(set(missing))
        print(f"ERROR: No queries found for domains: {', '.join(unique_missing)}")
        print(f"       Check {QUERIES_FILE}")
        sys.exit(1)

    run_pipeline(
        phases_to_run,
        domain_queries,
        args.attack,
        max_queries_per_domain=args.max_queries,
    )
