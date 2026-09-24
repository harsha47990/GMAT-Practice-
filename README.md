# GMAT Focus Mock Exam

A local, single-user GMAT practice app with adaptive difficulty, real section
timers, an on-screen calculator, scoring, and an AI report card.

---

## Features
- **Full Mock** (Focus Edition): Quantitative → Verbal → Data Insights, each timed and adaptive (IRT/Rasch).
- **Practice Mode**: pick a topic (PS, DS, CR, RC, MSR, TA, GI, TPA), length, timed on/off.
- **Adaptive engine**: ability (theta) is estimated by MLE; the next item maximizes information at your current ability.
- **On-screen calculator**: available in Data Insights (mirrors the real exam).
- **Review & edit**: change up to 3 answers per section before confirming.
- **Encrypted question bank**: `data/bank.dat` is gzipped + Fernet-encrypted, so questions/answers are not human-readable on disk.
- **AI report card**: per-topic, per-difficulty, per-tag accuracy, pacing analysis, and a prioritized study plan.

---

## 1. One-time setup
```powershell
cd GMAT
python -m venv .venv; .\.venv\Scripts\Activate.ps1   # optional but recommended
pip install -r requirements.txt
```
`.env` already contains the Foundry credentials and the model (`GMAT_MODEL=gpt-5.6-sol`)
used for AI generation and the report card. Edit it if your endpoint/key changes.

---

## 2. Run the app (the main thing you'll use)

```powershell
python -m uvicorn app:app --port 8100
```
Then open **http://127.0.0.1:8100** in your browser.

| Flag | Use | Example |
| --- | --- | --- |
| `--port <n>` | Change the port | `--port 9000` |
| `--host <ip>` | Expose on your network (default `127.0.0.1`) | `--host 0.0.0.0` |
| `--reload` | Auto-restart on code changes (development) | `--reload` |

Example (dev mode, reachable from other devices on your LAN):
```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8100 --reload
```
Stop the server with **Ctrl+C**.

---

## 3. Command reference

All commands are run from the `GMAT` folder. `python -m <module>` runs a script
inside the project.

### 3.1 `build_bank` — build/import the encrypted question bank
Turns a JSON file of questions into the encrypted `data/bank.dat`.

```powershell
python -m authoring.build_bank [--from <file.json>] [--merge]
```

| Flag | Use |
| --- | --- |
| `--from <file>` | Source JSON file to import. |
| `--merge` | Add to the existing bank instead of replacing it (skips duplicates). |

Examples:
```powershell
# Import your own question file, replacing the bank
python -m authoring.build_bank --from my_questions.json

# Add a new batch on top of what's already there
python -m authoring.build_bank --from more_questions.json --merge
```
> The original seed file was deleted after the first build, so running this with
> no `--from` will show a helpful message. Use the AI generator (below) or your own JSON.

---

### 3.2 `generate_questions` — create new questions with AI (dedup-aware)
Reads the existing bank, shows the model the questions already present so it
avoids repeats, generates fresh ones, and merges them into the encrypted bank.

```powershell
python -m authoring.generate_questions [--type <T>] [--band <1-5>] [--count <n>]
                                       [--target <n>] [--model <name>] [--preview <file>]
```

| Flag | Use |
| --- | --- |
| `--type <T>` | Question type: `PS`, `DS`, `CR`, `RC`, `MSR`, `TA`, `GI`, `TPA`. |
| `--band <1-5>` | Difficulty band: 1=Very Easy … 5=Very Hard. |
| `--count <n>` | How many to generate (default 10). |
| `--target <n>` | Auto mode: top **every** type up to ~n questions, spread across bands. |
| `--model <name>` | Override the model (default `gpt-5.6-sol` from `.env`). |
| `--preview <file>` | Write results to a JSON file **without** changing the bank (for review). |

Examples:
```powershell
# 10 hard Critical Reasoning questions, added to the bank
python -m authoring.generate_questions --type CR --band 4 --count 10

# 5 medium Problem Solving questions — preview only, bank untouched
python -m authoring.generate_questions --type PS --band 3 --count 5 --preview preview.json

# Grow the whole bank toward ~100 questions per type (runs many batches)
python -m authoring.generate_questions --target 100
```
> Recommended first: use `--preview` on a small batch to eyeball AI quality before mass-generating.

---

### 3.3 `validate_bank` — health-check the bank
Decrypts the bank in memory and prints counts + any problems (missing fields,
bad answer index, duplicates). It never prints the answers.

```powershell
python -m authoring.validate_bank [<file.json>]
```

| Argument | Use |
| --- | --- |
| *(none)* | Validate the live encrypted bank `data/bank.dat`. |
| `<file.json>` | Validate a raw JSON file before importing it. |

Examples:
```powershell
# Check the current bank
python -m authoring.validate_bank

# Check a file you're about to import
python -m authoring.validate_bank my_questions.json
```
Sample output:
```
Total: 28
By type:  {'PS': 10, 'DS': 5, 'CR': 6, 'RC': 4, 'TA': 1, 'GI': 1, 'MSR': 1}
By band:  {1: 6, 2: 8, 3: 10, 4: 4}
No blocking errors.
```

---

## 4. Typical workflows

**Just take an exam:**
```powershell
python -m uvicorn app:app --port 8100
```

**Add more questions, then practice:**
```powershell
python -m authoring.generate_questions --type RC --band 3 --count 8
python -m authoring.validate_bank
python -m uvicorn app:app --port 8100
```

**Build a big bank from scratch:**
```powershell
python -m authoring.generate_questions --target 100
python -m authoring.validate_bank
```

---

## 5. Project layout
```
app.py                    FastAPI backend + session store
config.py                 exam blueprint, scoring, paths
engine/
  bank.py                 encrypted read/write + dedup helpers
  adaptive.py             IRT/Rasch ability + item selection
  scoring.py              theta -> section score -> total
  session.py              exam state machine, timers, review/edit
analysis/report_card.py   AI diagnostic report
authoring/
  build_bank.py           JSON -> encrypted bank
  generate_questions.py   dedup-aware AI generation
  validate_bank.py        bank/JSON health check
models/                   self-contained LLM layer (providers + config)
static/                   web UI (HTML/CSS/JS + calculator)
data/                     bank.dat, bank.key (gitignored), attempts/
reports/                  saved AI report cards
```

---

## 6. Notes
- **Question type codes**: `PS` Problem Solving · `DS` Data Sufficiency · `CR` Critical Reasoning · `RC` Reading Comprehension · `MSR` Multi-Source Reasoning · `TA` Table Analysis · `GI` Graphics Interpretation · `TPA` Two-Part Analysis.
- **Encryption key**: `data/bank.key` (gitignored). Deleting it makes the existing `bank.dat` unreadable — back it up if the bank matters to you.
- **No plaintext leaks**: the generator writes new items straight into the encrypted bank. The only readable output is if you opt in with `--preview`.
- Graphical Data Insights formats (Table/Graphics/Multi-Source) are approximated as single-answer multiple choice so the engine and UI stay uniform.
- Attempt results are saved to `data/attempts/`; AI report cards to `reports/`.
