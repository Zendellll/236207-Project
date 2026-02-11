# Experiment Pipeline

Automated pipeline for running Reasoning Poisoning experiments across all attack phases.

## What This Does

Runs your partner's pre-built attack data through a RAG pipeline with multiple LLM models
(safe vs abliterated), comparing how each model responds to poisoned vs clean context.
Results are saved as structured CSVs for analysis.

## Setup

```bash
cd experiment_pipeline/

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Make sure Ollama is running (in another terminal if needed)
ollama serve

# Pull required models
ollama pull nomic-embed-text
ollama pull deepseek-r1:7b
ollama pull deepseek-r1:8b
ollama pull huihui_ai/deepseek-r1-abliterated:7b
ollama pull huihui_ai/deepseek-r1-abliterated:8b
```

## Usage

Always run from inside `experiment_pipeline/`:

```bash
cd experiment_pipeline/
source venv/bin/activate
```

### List All Available Phases

```bash
python run_pipeline.py --list
```

Shows all 66 discovered phases with file counts.

### Run Specific Phases

```bash
# Run baseline (clean, no attacks)
python run_pipeline.py --phases clean

# Run baseline + generic poisoned
python run_pipeline.py --phases clean poisoned

# Run one specific attack combination
python run_pipeline.py --phases multiple-bots/high-real-upvotes/fake_authority-attack

# Run multiple specific attacks in one go
python run_pipeline.py --phases clean single-bot/low-fake-upvotes/severe_safety-attack multiple-bots/high-real-upvotes/paradox-attack
```

### Filter by Group or Attack Type

```bash
# All single-bot experiments (32 phases)
python run_pipeline.py --group single-bot

# All multiple-bots experiments (32 phases)
python run_pipeline.py --group multiple-bots

# One attack type across ALL bot types and upvote levels
python run_pipeline.py --attack severe_safety-attack
python run_pipeline.py --attack fake_authority-attack
```

### Run Everything

```bash
# All 66 phases (takes a long time!)
python run_pipeline.py --all
```

### Clean Up Runtime Files

```bash
./cleanup.sh
```

## Attack Data Structure

The pipeline reads from `../mock_internet/` (your partner's data, don't modify):

```
../mock_internet/
├── clean/                         ← baseline, no attacks (54 files)
├── poisoned/                      ← generic poisoned version (54 files)
│
├── single-bot/                    ← 1 fake bot injected
│   ├── low-real-upvotes/
│   │   ├── attribute-attack/      ← fake certifications/awards
│   │   ├── fake_authority-attack/ ← fabricated official sources
│   │   ├── mild_safety-attack/    ← subtle safety concerns about competitors
│   │   ├── negative_smear-attack/ ← negative info about competitors
│   │   ├── paradox-attack/        ← contradictory information
│   │   ├── recency-attack/        ← fake "recent" updates
│   │   ├── severe_safety-attack/  ← urgent danger warnings
│   │   └── strike_logic-attack/   ← logical constraints ("only X available")
│   ├── low-fake-upvotes/          (same 8 attacks)
│   ├── high-real-upvotes/         (same 8 attacks)
│   └── high-fake-upvotes/         (same 8 attacks)
│
└── multiple-bots/                 ← multiple coordinated fake bots
    ├── low-real-upvotes/          (same 8 attacks)
    ├── low-fake-upvotes/          (same 8 attacks)
    ├── high-real-upvotes/         (same 8 attacks)
    └── high-fake-upvotes/         (same 8 attacks)
```

### Attack Dimensions

| Dimension | Options | Description |
|-----------|---------|-------------|
| **Bot count** | `single-bot`, `multiple-bots` | How many fake sources are injected |
| **Upvote level** | `low-real`, `low-fake`, `high-real`, `high-fake` | Credibility signals on the fake content |
| **Attack type** | 8 types (see below) | The manipulation strategy used |

### Attack Types Explained

| Attack | What It Does |
|--------|-------------|
| `attribute-attack` | Adds fake certifications, awards, or credentials |
| `fake_authority-attack` | Fabricates official sources (fake news, government notices) |
| `mild_safety-attack` | Adds subtle safety concerns about competitors |
| `negative_smear-attack` | Spreads negative misinformation about competitors |
| `paradox-attack` | Injects contradictory information to confuse reasoning |
| `recency-attack` | Adds fake "latest update" to exploit recency bias |
| `severe_safety-attack` | Adds urgent danger warnings about competitors |
| `strike_logic-attack` | Creates logical constraints ("only X available due to strike") |

### Total: 66 Phases

- 1 baseline (clean)
- 1 generic poisoned
- 32 single-bot (4 upvote levels x 8 attack types)
- 32 multiple-bots (4 upvote levels x 8 attack types)

## How It Works

For each phase:

1. **Reset** - Deletes vector database (no data leakage between phases)
2. **Build** - Creates fresh vector database from that phase's 54 .txt files using `nomic-embed-text` embeddings
3. **Query** - For each of the 30 test queries:
   - Retrieves top 20 relevant chunks via RAG
   - Sends context + query to each of the 4 models
   - Parses the response into Chain-of-Thought and Final Answer
4. **Save** - Writes all results to `logs/results_{phase_name}.csv`

Each phase = 30 queries x 4 models = **120 LLM calls**.

## Output

Results are saved to `logs/`:

```
logs/
├── results_clean.csv
├── results_poisoned.csv
├── results_single-bot_low-real-upvotes_attribute-attack.csv
├── results_single-bot_low-real-upvotes_fake_authority-attack.csv
├── results_single-bot_high-fake-upvotes_severe_safety-attack.csv
├── results_multiple-bots_high-real-upvotes_paradox-attack.csv
├── ...
└── pipeline_summary.txt
```

### CSV Columns

| Column | Description |
|--------|-------------|
| `phase` | Attack phase name (e.g. `single-bot/high-fake-upvotes/attribute-attack`) |
| `query_id` | Query number (1-30) |
| `query` | The question asked |
| `model` | Model name |
| `model_type` | `safe` or `abliterated` |
| `chain_of_thought` | Model's reasoning (extracted from `<think>` tags) |
| `final_answer` | Model's final recommendation |
| `full_response` | Complete raw response |
| `response_time_sec` | Inference time in seconds |
| `sources_used` | Which documents were retrieved by RAG |
| `timestamp` | When the result was generated |

## Models

| Model | Type | Description |
|-------|------|-------------|
| `deepseek-r1:7b` | Safe | Standard safety-aligned reasoning model |
| `deepseek-r1:8b` | Safe | Larger safety-aligned variant |
| `huihui_ai/deepseek-r1-abliterated:7b` | Abliterated | Safety guardrails removed |
| `huihui_ai/deepseek-r1-abliterated:8b` | Abliterated | Larger abliterated variant |

## Customization

**Change models** - Edit `MODELS_TO_TEST` in `experiment.py`

**Change queries** - Edit `queries.txt` (lines starting with `#` or `---` are ignored)

**Change RAG settings** - In `experiment.py`:
```python
CHUNK_SIZE = 1000      # Characters per text chunk
CHUNK_OVERLAP = 200    # Overlap between chunks
RAG_RESULTS = 20       # Number of chunks retrieved per query
```

## Troubleshooting

**"No module named 'chromadb'"** - Activate the venv: `source venv/bin/activate`

**"Ollama connection failed"** - Start Ollama: `ollama serve`

**"Model not found"** - Pull it: `ollama pull deepseek-r1:7b`

**Too slow?** - Reduce models in `experiment.py` or queries in `queries.txt`

**Want to re-run a phase?** - Just run it again, the database resets automatically
