# Main Experiment Pipeline — Reasoning Poisoning

This folder runs the full experiment: **run phases** (RAG + LLM per domain/attack) and optionally **judge** results to compute Attack Success Rate (ASR).

One pipeline for all domains: **20 technical domains** (partner’s) and **10 tourism domains** (yours). Same query CSV, same phase layout, same run logic. Use flags to run “all”, “only technical”, or “only tourism”.

---

## Prerequisites

1. **Python 3** with: `ollama`, `chromadb`, `pandas`.  
   Judge script also uses `matplotlib`, `seaborn` (optional, for charts).

   ```bash
   pip install ollama chromadb pandas
   # optional, for judge charts:
   pip install matplotlib seaborn
   ```

2. **Ollama** installed and running, with these models available:
   - **Experiment:** `deepseek-r1:8b` (used by `experiment.py`)
   - **Embeddings:** `nomic-embed-text`
   - **Judge (optional):** `mistral-nemo` (or override with `--judge-model`)

   Pull if needed:
   ```bash
   ollama pull deepseek-r1:8b
   ollama pull nomic-embed-text
   ollama pull mistral-nemo
   ```

3. **Ollama server** running (e.g. `ollama serve`).  
   For long context and less RAM you can use:
   ```bash
   ./run_ollama_with_kv_quantization.sh
   ```

---

## 1. Run the experiment

From the **`main_exp`** directory:

```bash
cd main_exp
```

### List what would run (no execution)

```bash
python run_main_experiment.py --list
```

### Run everything (all 30 domains, clean + all attacks)

```bash
python run_main_experiment.py all
```

### Run only the 20 technical domains (partner’s)

```bash
python run_main_experiment.py all --technical-only
```

### Run only the 10 tourism domains

```bash
python run_main_experiment.py all --tourism-only
```

### Skip clean baseline (only attack phases)

```bash
python run_main_experiment.py all --skip-clean
python run_main_experiment.py all --technical-only --skip-clean
python run_main_experiment.py all --tourism-only --skip-clean
```

### Run one attack type only

```bash
python run_main_experiment.py attribute
python run_main_experiment.py fake_authority
python run_main_experiment.py severe_safety
```

### Run a single domain

```bash
python run_main_experiment.py all --domain kubernetes-crashloopbackoff
python run_main_experiment.py all --domain boutique-winery
```

### Quick / debug runs (fewer domains, fewer queries)

```bash
python run_main_experiment.py all --max-domains 2 --max-queries 1
python run_main_experiment.py all --tourism-only --max-queries 2
```

### Options summary

| Option | Meaning |
|--------|--------|
| `all` | All three attack types (attribute, fake_authority, severe_safety) |
| `attribute` / `fake_authority` / `severe_safety` | Only that attack type |
| `--list` | List phases (respects other flags), then exit |
| `--skip-clean` | Do not run clean baseline phases |
| `--technical-only` | Only the 20 technical domains |
| `--tourism-only` | Only the 10 tourism domains |
| `--domain <slug>` | Only this domain (e.g. `kubernetes-crashloopbackoff`, `boutique-winery`) |
| `--group single-bot` / `--group multiple-bots` | Only that bot group |
| `--max-domains N` | Only first N domains (for quick runs) |
| `--max-queries N` | Only first N queries per domain (for quick runs) |

You cannot use `--technical-only` and `--tourism-only` together.

---

## 2. Outputs

- **Directory:** `main_exp/logs/`
- **Per phase:** `results_<domain>_<group>_<upvote>_<attack>.csv`  
  Columns include: `phase`, `query_id`, `query`, `model`, `final_answer`, `full_response`, `sources_used`, etc.
- **Summary:** `logs/pipeline_summary.txt` (what ran, what failed, duration)

---

## 3. Judge (evaluate ASR)

After you have result CSVs in `logs/`, you can run the judge to see whether the model recommended the target (e.g. LocalGems for tourism) and get Attack Success Rate (ASR) tables and a chart:

```bash
cd main_exp
python run_judge.py
```

- Reads: `logs/results_*.csv`
- Writes: `logs/judged_results.csv`, and optionally `logs/asr_results.png` (if matplotlib/seaborn installed)
- Default target: `LocalGems`. Override: `python run_judge.py --target "LocalGems"`
- Other options: `--judge-model`, `--pattern`, `--exclude-queries`, `--tourism-only`, `--output`

---

## 4. Data and config (what the pipeline uses)

- **Queries:** `source-gather/20_domains_50_queries.csv`  
  One CSV for all domains (technical + tourism). Columns: `Domain`, `Query ID`, `Query`. 50 queries per domain.
- **Mock internet (per domain):**  
  `mock_internet/<domain>/clean`  
  `mock_internet/<domain>/single-bot` and `mock_internet/<domain>/multiple-bots`  
  Under each: `no-upvotes`, `low-fake-upvotes`, `high-fake-upvotes` → then `attribute-attack`, `fake_authority-attack`, `severe_safety-attack`.
- **Vector DB (created at run time):** `vector_db_active/` (ChromaDB, built from the phase’s `.txt` files).

Environment overrides (optional):

- `EXPERIMENT_MOCK_INTERNET_DIR` — root of mock internet (default: `main_exp/mock_internet`)
- `EXPERIMENT_LOGS_DIR` — where to write result CSVs (default: `main_exp/logs`)
- `EXPERIMENT_DB_PATH` — ChromaDB path (default: `main_exp/vector_db_active`)
- `EXPERIMENT_CONTEXT_MODE` — e.g. `rag` or `attack_plus_random_clean` (see `experiment.py`)

---

## 5. Quick reference: “run the whole pipeline”

**Technical domains only (partner’s), no clean, full queries:**

```bash
cd main_exp
python run_main_experiment.py all --technical-only --skip-clean
```

**Tourism domains only, no clean:**

```bash
cd main_exp
python run_main_experiment.py all --tourism-only --skip-clean
```

**Then judge (e.g. tourism results):**

```bash
python run_judge.py --tourism-only
```

That’s the full pipeline: run phases → then judge.
