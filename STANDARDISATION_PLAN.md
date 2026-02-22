# Standardisation Plan: Merge Your Work with Partner's Codebase

**Goal:** Work from the partner's latest commit (origin/main), keep your attacks and queries, and run his pipeline with your tourism data added.

---

## 1. Git: Base on Partner's Latest

- **Action:** Merge or rebase your branch onto `origin/main` so the project is based on his latest commit.
- **Steps:**
  1. Stash or commit your current work (so nothing is lost).
  2. `git fetch origin`
  3. `git checkout main` then `git merge origin/main` (or `git rebase origin/main` if you prefer).
  4. Resolve conflicts: keep his structure for `experiment_pipeline/` and `main_exp/`; treat your additions as new files or additive changes.
- **Result:** Repo is on his main. His `main_exp/run_main_experiment.py` and `main_exp/experiment.py` are the source of truth for the “one pipeline” run.

---

## 2. Where Your Data Lives (Attacks + Queries)

His pipeline reads:

- **Data:** `main_exp/mock_internet/<domain>/` (single-bot / multiple-bots / no-upvotes, low-fake-upvotes, high-fake-upvotes / attribute-attack, fake_authority-attack, severe_safety-attack).
- **Queries:** `main_exp/source-gather/20_domains_50_queries.csv` with columns `Domain`, `Query ID`, `Query`. Domain names are mapped to folder slugs via `DOMAIN_NAME_TO_SLUG` in `run_main_experiment.py`.

To “add your work” without breaking his:

- **Attacks (mock data):** Put your 10 tourism domains **inside** `main_exp/mock_internet/` so the same discovery sees them.
- **Queries:** Add your 10 tourism domains (and their 50 queries each) into the same system: either extend the CSV + `DOMAIN_NAME_TO_SLUG`, or add a small fallback that loads from per-domain files for tourism only.

---

## 3. Concrete Steps (Code and Data)

### Step A: Add tourism domains into `main_exp/mock_internet/`

- **Source:** Your current `mock_internet/` at repo root:  
  `taxi-driver`, `food-tour-guide`, `surf-school`, `scuba-diving-center`, `boutique-winery`, `cooking-class`, `glamping`, `historical-tour-guide`, `jeep-tours`, `vacation-photographer`.
- **Action:** Copy these 10 directories (with their `single-bot/`, `multiple-bots/`, and all attack subfolders) into `main_exp/mock_internet/`.
- **Do not** remove his 20 tech domains; you will have 30 domains under `main_exp/mock_internet/` in total.
- **Optional later:** If you want to avoid duplication, you can add a configurable `MOCK_INTERNET_DIR` (env or CLI) so his 20 stay in `main_exp/mock_internet/` and yours stay in root `mock_internet/`; for the first version, copying is simpler.

### Step B: Add tourism domains to the runner and queries

**Option 1 (recommended): Single CSV for all 30 domains**

- **File:** `main_exp/source-gather/20_domains_50_queries.csv` (or a new name like `30_domains_50_queries.csv`).
- **Action:**
  1. Keep his 20 tech domains and 50 queries each (1000 rows).
  2. Append your 10 tourism domains × 50 queries (500 rows) from your existing tourism query file/CSV. Use the **exact** domain names you will add to `DOMAIN_NAME_TO_SLUG` (e.g. `Taxi Driver`, `Food Tour Guide`, …).
  3. In `main_exp/run_main_experiment.py`, add the 10 entries to `DOMAIN_NAME_TO_SLUG`, for example:

```python
# Tourism domains (add to existing dict)
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
```

- **Optional:** Rename the CSV to something like `30_domains_50_queries.csv` and set `QUERIES_FILE` in `run_main_experiment.py` to that path.

**Option 2: Keep tourism queries in per-domain files**

- **Action:** In `run_main_experiment.py`, in `load_domain_queries()`:
  1. Load the CSV as now (for his 20 domains).
  2. For each slug that does **not** appear in the CSV, try to load `main_exp/queries/domains/<slug>.txt` (one query per line) and assign query IDs 1..50. Add the 10 tourism slugs to a list or a second “domain name → slug” mapping used only for file-based loading.
- **Data:** Copy your existing `experiment_pipeline/queries/domains/*.txt` (taxi-driver, food-tour-guide, …) into `main_exp/queries/domains/` (create the dir if needed).
- **Result:** His 20 domains use CSV; your 10 use the same pipeline with per-domain txt files. No need to change the CSV content.

Choose one of the two options and implement it consistently.

### Step C: Optional – run only tech or only tourism

- In `run_main_experiment.py`, add a simple filter so you can run “only our domains” or “only his” without editing code each time, e.g.:
  - `--only-tourism`: restrict to the 10 tourism slugs.
  - `--only-tech`: restrict to the 20 tech slugs (current list).
- Implement by filtering the list returned by `discover_domains()` (or the phases list) before running.

---

## 4. What to Drop or Keep from Your Current Repo

- **Keep (and integrate as above):**
  - Your 10 tourism domains’ mock data (→ `main_exp/mock_internet/`).
  - Your tourism queries (→ CSV or `main_exp/queries/domains/*.txt`).
  - Any attack-design docs you want to keep (e.g. under `main_exp/` or `docs/`); they don’t affect the runner.
- **Do not rely on for the “standard” run:**
  - `experiment_pipeline/run_domain_pipeline.py` (replaced by `main_exp/run_main_experiment.py` once your data is in main_exp).
  - `experiment_pipeline/queries/domains/*.txt` **as the primary source** (either move into main_exp and use Option 2, or merge into CSV and use Option 1).
- **Optional to keep in repo:**
  - Root `mock_internet/` as a backup copy of tourism data, or remove it after copying into `main_exp/mock_internet/` to avoid confusion.
  - `experiment_pipeline/run_domain_pipeline.py` as an alternative entry point if you later want a second pipeline; document that the “canonical” run is `main_exp/run_main_experiment.py`.

---

## 5. How to Run After Standardisation

- **List phases (all 30 domains):**
  ```bash
  cd main_exp
  python run_main_experiment.py --list
  ```
- **Run all attacks (all 30 domains, clean + attacks):**
  ```bash
  python run_main_experiment.py all
  ```
- **Run only tourism (if you added `--only-tourism`):**
  ```bash
  python run_main_experiment.py all --only-tourism
  ```
- **Run only one domain (e.g. taxi):**
  ```bash
  python run_main_experiment.py all --domain taxi-driver
  ```
- **Skip clean (attacks only):**
  ```bash
  python run_main_experiment.py all --skip-clean
  ```

Same code path as his; your attacks and queries are just extra domains and rows (or files) in that pipeline.

---

## 6. Checklist Summary

| # | Task | Owner |
|---|------|--------|
| 1 | Git: merge/rebase onto origin/main, resolve conflicts | You |
| 2 | Copy 10 tourism domain dirs from mock_internet/ → main_exp/mock_internet/ | You |
| 3 | Add 10 tourism entries to DOMAIN_NAME_TO_SLUG in run_main_experiment.py | You |
| 4a | **Option 1:** Append 500 tourism query rows to CSV; optionally rename CSV and QUERIES_FILE | You |
| 4b | **Option 2:** Add main_exp/queries/domains/*.txt and extend load_domain_queries() for file fallback | You |
| 5 | (Optional) Add --only-tourism / --only-tech to run_main_experiment.py | You |
| 6 | Test: run_main_experiment.py --list shows 30 domains; run one tourism domain end-to-end | You |

After this, you have one codebase (his latest), one pipeline (his runner), with your attacks and queries integrated so you can run his code with your data added to the repo.
