# Safe Merge Guide: Keep Your Queries and mock_internet

This guide makes sure **your queries** (`experiment_pipeline/queries/`) and **your tourism attacks** (root `mock_internet/` — the 10 domain folders) are **never deleted** when merging with main and tweaking his code.

---

## Why they could be lost (and how we avoid it)

| Risk | What could happen | How we avoid it |
|------|-------------------|------------------|
| Merge overwrites | You run `git checkout origin/main -- .` or accept "theirs" everywhere | We **never** checkout his branch over the whole repo. We merge and resolve carefully. |
| Your data is untracked | After merge, your files are still on disk but not in git; a later `git clean -fd` could remove them | We **commit** your data to a **backup branch** first, and later **copy** (not move) into `main_exp/`. |
| You delete "duplicates" | You think root `mock_internet/` is redundant and delete it before `main_exp/` has a copy | We **copy first, delete never** (or only after you've run his pipeline and confirmed everything works). |

---

## Step 1: Backup your data (do this first)

Run the backup script **before** any merge. It copies your data to a folder that git does not touch:

```bash
cd /Users/matanlevi/Downloads/236207-Project
python3 scripts/backup_our_data.py
```

This creates:

- **`_backup_our_data/<timestamp>/queries/`** — copy of `experiment_pipeline/queries/domains/*.txt`
- **`_backup_our_data/<timestamp>/mock_internet/`** — copy of your 10 tourism domains from `mock_internet/`

Keep `_backup_our_data/` until you have verified that `main_exp/` has the same data and the pipeline runs. You can add `_backup_our_data/` to `.gitignore` so it never gets committed.

**Optional (belt and suspenders):** Commit your data to a backup branch so it's in git forever:

```bash
git checkout -b backup-tourism-data
git add experiment_pipeline/queries/domains/
git add mock_internet/taxi-driver mock_internet/food-tour-guide mock_internet/surf-school \
      mock_internet/scuba-diving-center mock_internet/boutique-winery mock_internet/cooking-class \
      mock_internet/glamping mock_internet/historical-tour-guide mock_internet/jeep-tours \
      mock_internet/vacation-photographer
git commit -m "Backup: our tourism queries and mock_internet (do not delete)"
git checkout main
```

If anything goes wrong later, you can always get the files back with:

```bash
git checkout backup-tourism-data -- experiment_pipeline/queries/domains/
git checkout backup-tourism-data -- mock_internet/taxi-driver mock_internet/food-tour-guide ...
```

---

## Step 2: Merge with main (without deleting your files)

Do **not** do any of the following:

- `git checkout origin/main -- .`   (overwrites whole working tree)
- `git reset --hard origin/main`    (loses uncommitted and your branch commits)
- Resolving conflicts by choosing "Accept Theirs" on `experiment_pipeline/queries` or `mock_internet/`

**Do this instead:**

1. Commit your current work (so your data is in git on your branch):
   ```bash
   git add experiment_pipeline/queries/domains/
   git add mock_internet/taxi-driver mock_internet/food-tour-guide mock_internet/surf-school \
         mock_internet/scuba-diving-center mock_internet/boutique-winery mock_internet/cooking-class \
         mock_internet/glamping mock_internet/historical-tour-guide mock_internet/jeep-tours \
         mock_internet/vacation-photographer
   git status   # check nothing else is staged by mistake
   git commit -m "Our tourism queries and mock_internet (keep after merge)"
   ```

2. Fetch and merge:
   ```bash
   git fetch origin
   git merge origin/main
   ```

3. If there are conflicts:
   - For files under **`experiment_pipeline/queries/`** or **`mock_internet/taxi-driver`**, … (your 10 domains): choose **ours** (keep your version).
   - For his files (`main_exp/`, his `experiment_pipeline/experiment.py`, etc.): take **theirs** or resolve by hand so his code wins.
   - Then `git add` the resolved files and `git commit`.

After the merge, your queries and your 10 domain folders should still be present in the tree. If they're not, restore from the backup branch or from `_backup_our_data/`.

---

## Step 3: Copy (don’t move) your data into main_exp

We **copy** your data into his layout so his pipeline can use it. We do **not** delete the originals yet.

1. **Copy tourism domains into his mock_internet:**
   ```bash
   for d in taxi-driver food-tour-guide surf-school scuba-diving-center boutique-winery cooking-class glamping historical-tour-guide jeep-tours vacation-photographer; do
     cp -R "mock_internet/$d" "main_exp/mock_internet/$d"
   done
   ```

2. **Copy your queries into main_exp** (for the CSV approach you’ll append to his CSV; for the file approach create his query dirs):
   ```bash
   mkdir -p main_exp/queries/domains
   cp experiment_pipeline/queries/domains/*.txt main_exp/queries/domains/
   ```

3. Add and commit these **new** copies in `main_exp/`:
   ```bash
   git add main_exp/mock_internet/taxi-driver main_exp/mock_internet/food-tour-guide ...
   git add main_exp/queries/domains/
   git commit -m "Add tourism domains and queries to main_exp (copy of our data)"
   ```

Now his code can run using `main_exp/mock_internet/` and `main_exp/queries/` or the combined CSV. Your original `experiment_pipeline/queries/` and root `mock_internet/` are still there and unchanged.

---

## Step 4: Tweak his code (only additive changes)

When you change his code to support your domains:

- **Do:** Add your 10 domains to `DOMAIN_NAME_TO_SLUG`, append your queries to the CSV (or wire in `main_exp/queries/domains/*.txt`), add optional flags like `--only-tourism`.
- **Don’t:** Delete or replace `experiment_pipeline/queries/` or the 10 tourism folders under root `mock_internet/` until you’ve run the full pipeline and are happy. Then you can delete them **only if you want** to avoid duplication; the canonical copy will be in `main_exp/`.

---

## Quick reference: where things live

| What | Location (keep until you’re sure) | Where his code will use it after merge |
|------|-----------------------------------|----------------------------------------|
| Your queries | `experiment_pipeline/queries/domains/*.txt` | `main_exp/queries/domains/*.txt` or rows in `main_exp/source-gather/...csv` |
| Your attacks (mock data) | `mock_internet/taxi-driver`, … (10 dirs) | `main_exp/mock_internet/taxi-driver`, … |

Backup (script): `_backup_our_data/<timestamp>/`  
Backup (git): branch `backup-tourism-data`

---

## If something was deleted by mistake

- **From backup folder:**  
  Copy back from `_backup_our_data/<timestamp>/queries/` and `_backup_our_data/<timestamp>/mock_internet/` into `experiment_pipeline/queries/domains/` and `mock_internet/`.

- **From backup branch:**  
  ```bash
  git checkout backup-tourism-data -- experiment_pipeline/queries/domains/
  git checkout backup-tourism-data -- mock_internet/taxi-driver mock_internet/food-tour-guide mock_internet/surf-school mock_internet/scuba-diving-center mock_internet/boutique-winery mock_internet/cooking-class mock_internet/glamping mock_internet/historical-tour-guide mock_internet/jeep-tours mock_internet/vacation-photographer
  ```

This way your queries and mock_internet stay safe and you can merge and tweak his code without losing them.
