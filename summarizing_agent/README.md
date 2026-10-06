# Summarizing Agent: RAG + Qwen3-VL → Applicant Dossier

This folder contains the **Summarizing Agent** for the AI-Assisted College
Admissions project (MSA 8770, Group 5). For one applicant, it reads the
application documents as page images, retrieves the relevant admissions
policies (RAG), and writes a **dossier** for an admissions officer.

- The model only **summarizes**. It never makes or suggests a decision.
- Code controls every step: it withholds documents the model must not see,
  checks every citation, and saves the result.
- Everything runs **locally** on your computer. Applicant data never leaves
  it, and all software used is free.

These instructions assume **nothing is installed yet**. Follow them in order.
Commands are for **macOS** (Terminal).

---

## Contents

1. [The pipeline](#1-the-pipeline)
2. [What is in this folder](#2-what-is-in-this-folder)
3. [One-time setup](#3-one-time-setup)
4. [Before every run](#4-before-every-run)
5. [Run it, step by step](#5-run-it-step-by-step)
6. [Read the dossier](#6-read-the-dossier)
7. [Stop everything](#7-stop-everything)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. The pipeline

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TRIGGER: applicant IDs (command line, or affected_ids.json from the     │
│          completeness check)                                             │
└──────────────────────────────────────────────────────────────────────────┘
                                  ↓
[1] CODE   Load applicant
           PostgreSQL → applicant record (status must be COMPLETE)
           + Documents JSONB (list of PDFs and their MinIO keys)
           ✗ not found / not COMPLETE → skip, log it
                                  ↓
[2] CODE   Withhold documents the model must never see
           • personal_statement.pdf      → humans only (POL-ESSAY-01)
           • common_app_application.pdf  → restricted data (gender, ethnicity, DOB, contact)
           ✓ sent: application form, transcript, test scores, AP record,
                   activities & awards, 2 recommendation letters, supplement
                                  ↓
[3] CODE   Prepare pages
           MinIO PDFs → PyMuPDF → PNG page images (in memory only)
           ✗ transcript or a letter missing / unreadable → HUMAN REVIEW (model not called)
                                  ↓
[4] RAG    Retrieve relevant policies
           nomic-embed-text embeds search questions → pgvector search over policies.yaml
           → e.g. POL-FT-01, POL-LOR-01, POL-TEST-01, POL-READ-01, POL-ID-01, POL-DATE-01
           (+ POL-ESSAY-01, POL-HUMAN-01 always; international/transfer rules only if they apply)
                                  ↓
[5] MODEL  Qwen3-VL 8B Instruct, one call per dossier section
           ┌─────────────────────────────────────────────────────────────────────────┐
           │ 5a  transcript + test scores + AP record + app form → academic_profile          │
           │ 5b  activities & awards                         → engagement_profile        │
           │ 5c  recommendation letters 1 & 2                → recommendation_profile    │
           │ 5d  university supplement                       → supplemental_essay_profile│
           │ 5e  retrieved policies + results of 5a–5d (text) → policy_assessment  (RAG) │
           │ 5f  results of 5a–5e (text)                     → strengths,                │
           │                                                    holistic_assessment      │
           └─────────────────────────────────────────────────────────────────────────┘
           • each call: only its own pages, an image map, section-specific instructions
           • no totals or counts given to the model (it reads them from the documents)
           • rules: no decision, no invention, no personal statement, no restricted data
                                  ↓
[6] CODE   Validate each section
           • valid JSON, all fields present
           • every citation → a page that was actually sent
           • the cited quote actually appears on that page
             (checked against the PDF's text by code; the text is never sent to the model)
           • policy IDs only from the retrieved set
           • no decision wording, no restricted data, no personal statement text
           ✗ fails → retry that section once → still fails → HUMAN REVIEW
                                  ↓
[7] CODE   Assemble the dossier (team schema: applicant_dossier)
           model sections from [5]
           + review_notes             ← things the model could not read clearly
           + applicant_demographics   ← applicant record (no restricted fields)
           + evidence_map             ← every citation, built by code
           + generated_at / updated_at
                                  ↓
[8] CODE   Save
           • applicant_dossier         ← the dossier (successful runs only)
           • dossier_generation_runs   ← every run: status, checks, timing, failures
           • summary_audit_log         ← each step
           • results/<APP_ID>_dossier.json ← readable copy
           • applicant status → DOSSIER_READY or HUMAN_REVIEW
                                  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ HARD STOP: the admissions officer reviews the dossier, reads the        │
│ personal statement, and makes the decision. The model never decides.    │
└──────────────────────────────────────────────────────────────────────────┘
```

| Step | Done by | Why |
|---|---|---|
| 1–3, 6–8 | Code | Objective rules: same result every time, easy to audit |
| 4 | Code + embedding model | Finds the relevant policies (the "R" in RAG) |
| 5 | Qwen3-VL (vision-language model) | Reads page images, writes the summaries (the "G" in RAG) |
| After the stop | Admissions officer | Final authority (POL-HUMAN-01) |

---

## 2. What is in this folder

```
summarizing_agent/
├── README.md                    ← this file
├── requirements.txt             ← Python packages
├── summarizing_agent.py         ← THE AGENT (the pipeline above)
├── test_summarizer_checks.py    ← tests for the code checks (no model needed)
├── evaluate_dossier.py          ← scores a dossier against the answer key
│
├── data/
│   ├── applicant_data_09302026_V3.csv   ← applicant records (team CSV)
│   ├── policies.yaml                    ← admissions policies (team file)
│   └── sample_docs/APP_001/             ← APP_001's 10 PDFs
│
├── setup/                       ← run once, in order (step 5.1)
│   ├── 1_create_simulated_minio.py      ← uploads the PDFs to MinIO
│   ├── 2_create_simulated_postgres.py   ← creates APP_001's record from the CSV
│   └── 3_create_policy_store.py         ← embeds policies.yaml into pgvector
│
├── answer_keys/APP_001.json     ← true values, read by hand from the PDFs
└── results/                     ← output (a reference run is already here)
```

**Setup scripts 1 and 2** stand in for the ingestion and completeness check
(the stage before this agent): they put the PDFs in MinIO and an applicant
record with status `COMPLETE` in PostgreSQL.

---

## 3. One-time setup

Do this once per computer. Each step ends with a check.

### 3.0 Get the code

The agent is on the `tran/summarizing-agent` branch of the team repository.
In Terminal:

```bash
git --version            # if missing, macOS will offer to install it; accept
cd ~
git clone https://github.com/kappasprouts/MSA8770-Fall2026.git
cd MSA8770-Fall2026
git checkout tran/summarizing-agent
cd summarizing_agent
ls                       # you should see README.md, summarizing_agent.py, setup/, data/ ...
```

Already cloned? Update instead: `cd ~/MSA8770-Fall2026 && git fetch && git checkout tran/summarizing-agent && git pull`.

### 3.1 Homebrew (macOS package manager)

Open **Terminal** (Applications → Utilities → Terminal) and check:

```bash
brew --version
```

If you get `command not found`, install it from <https://brew.sh> (copy the
command shown on the site into Terminal), then close and reopen Terminal.

### 3.2 Python 3

```bash
python3 --version
```

You need **3.10 or newer**. If it's missing or older: `brew install python`.

### 3.3 Docker Desktop (runs PostgreSQL)

1. Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Open it and wait until it says it's running.
3. Check:

```bash
docker --version
```

### 3.4 PostgreSQL with pgvector

Create the database container. It uses the **pgvector** image, which the
policy search (RAG) needs. The name, password, and database below match the
defaults in the scripts.

```bash
docker run -d --name msa8770-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=riverview_admissions \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

Check:

```bash
docker ps
```

You should see `msa8770-postgres` with status `Up`.

> **Already have a container called `msa8770-postgres`?** Check its image with
> `docker ps -a`. If the image is `pgvector/pgvector:pg16`, skip this step. If
> it's plain `postgres`, remove it (`docker rm -f msa8770-postgres`) and run the
> command above. This deletes that container's data.

### 3.5 MinIO (stores the PDFs)

```bash
brew install minio
minio --version
```

### 3.6 Ollama and the two models

1. Download and install [Ollama](https://ollama.com/download), then open it
   once. It keeps running in the background.
2. Download the two models (about 6.4 GB in total; this can take a while):

```bash
ollama pull qwen3-vl:8b-instruct
ollama pull nomic-embed-text
```

3. Check:

```bash
ollama list
```

You should see both `qwen3-vl:8b-instruct` and `nomic-embed-text`.

> **Use `qwen3-vl:8b-instruct`, not `qwen3-vl:8b`.** On Ollama, the plain
> `qwen3-vl:8b` is the *Thinking* version. It reasons silently for thousands of
> tokens before answering, and in testing it never finished a dossier. The
> *Instruct* version answers directly.

### 3.7 Python environment

```bash
cd ~/MSA8770-Fall2026/summarizing_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Check (should print nothing but `ok`):

```bash
python -c "import psycopg2, pymupdf, minio, requests, yaml; print('ok')"
```

> If you cloned the repository somewhere other than your home folder, adjust
> the `cd` path. All commands in this README are run from inside the
> `summarizing_agent` folder.

---

## 4. Before every run

### 4.1 Free up memory

**Quit Chrome and other large apps.** The model needs about 9 GB of memory.
On a 16 GB Mac with Chrome open, the model ran 2–4 times slower.

### 4.2 Start PostgreSQL

Open Docker Desktop, then:

```bash
docker start msa8770-postgres
```

### 4.3 Start MinIO

Open a **second Terminal window** and leave it running the whole time:

```bash
cd ~/MSA8770-Fall2026/summarizing_agent
MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin \
  minio server ./minio-data --address :9000 --console-address :9001
```

You can browse the stored files at <http://localhost:9001>
(user `minioadmin`, password `minioadmin`).

### 4.4 Check Ollama

```bash
ollama list
```

If you get an error, open the Ollama app.

### 4.5 Activate the Python environment

In your **first** Terminal window:

```bash
cd ~/MSA8770-Fall2026/summarizing_agent
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`.

---

## 5. Run it, step by step

### 5.1 Setup scripts (in order)

**Setup 1: upload the PDFs to MinIO**

```bash
python setup/1_create_simulated_minio.py
```

Creates the bucket `applicant-documents` and uploads the 10 PDFs in
`data/sample_docs/APP_001/`. Expected ending:

```
Objects in bucket 'applicant-documents':
  APP_001/activities_and_awards.pdf
  ...
  APP_001/university_supplement.pdf

MinIO seed completed successfully.
```

**Setup 2: create APP_001's record in PostgreSQL**

```bash
python setup/2_create_simulated_postgres.py
```

Creates the table `simulated_applicant_data` and loads APP_001 **from the
CSV**, with status `COMPLETE`. Its document list contains all 10 PDFs; the
agent itself withholds two of them. Expected ending:

```
Status:        COMPLETE

MinIO document references:
  application_form -> APP_001/application_form.pdf
  common_app      -> APP_001/common_app_application.pdf
  ...
  personal_statement -> APP_001/personal_statement.pdf

PostgreSQL simulation completed successfully.
```

**Setup 3: build the policy store (RAG knowledge base)**

```bash
python setup/3_create_policy_store.py
```

Turns each of the 11 policies in `data/policies.yaml` into a vector with
`nomic-embed-text` and stores them in PostgreSQL (`policy_chunks` table).
Expected ending:

```
Stored 11 policy chunks (version 1.0).
  POL-DATE-01  Date Consistency
  ...
  POL-TR-01    Transfer Core Materials
```

You only need to run the setup scripts again if you reset the database, add
applicants, or change `policies.yaml`.

### 5.2 Optional: run the tests

Checks the code-level controls (withholding, citation checks, no decisions,
dossier assembly). Takes under a second and doesn't use the model.

```bash
python -m pytest test_summarizer_checks.py -q
```

Expected: `25 passed`.

### 5.3 Run the agent

```bash
python summarizing_agent.py APP_001
```

This takes **about 10 minutes** (with Chrome closed). To also save the screen
output to a file:

```bash
python summarizing_agent.py APP_001 | tee results/my_run_output.txt
```

**What you will see:**

```
[1] Applicant APP_001, status COMPLETE
[2] 10 documents: 8 for the model, 2 withheld
    withheld: common_app_application.pdf       (restricted demographic/contact data)
    withheld: personal_statement.pdf           (POL-ESSAY-01 personal statement (humans only))
[3] Rendering pages at 1.5x (memory only)
    ✓ application_form.pdf                     1 page(s)
    ...
[4] RAG: retrieved 8 policies: POL-DATE-01, POL-ESSAY-01, POL-FT-01, ...
[5] qwen3-vl:8b-instruct: one call per section (each validated, retried once if needed)
    [1/2] academic (5 page image(s)) ....  70s, 939 tokens  ✓
    [1/2] engagement (2 page image(s)) ....  105s, 1055 tokens  ✓
    [1/2] recommendation (2 page image(s)) ..  72s, 598 tokens  ✓
    [1/2] supplement (1 page image(s)) ..  50s, 504 tokens  ✓
    [1/2] policy (text only) ....  119s, 1067 tokens  ✓
    [1/2] synthesis (text only) .  73s, 441 tokens  ✓
[6] ✓ All sections passed validation (29 citations checked)
[7] Dossier assembled: 0 review note(s)
[8] Saved DOSSIER_READY → applicant_dossier + dossier_generation_runs, results/APP_001_dossier.json

[HARD STOP] Dossiers are advisory. An admissions officer makes every decision.
```

The dots show the model writing. Times and token counts will differ a little.

**If a section shows `✗`:** that's the validation working. It lists the
problem (for example, a quote that isn't on the cited page), and the section is
retried once with the problem pointed out. If it fails twice, the run ends with
`HUMAN_REVIEW_AI_FAILED`: nothing is saved to `applicant_dossier`, and the
details are kept in `dossier_generation_runs`.

**Run it again** for the same applicant: after a successful run the applicant's
status is `DOSSIER_READY`, so add `--force`:

```bash
python summarizing_agent.py APP_001 --force
```

### 5.4 Score the dossier

Compares the dossier with the true values in `answer_keys/APP_001.json` (read
by hand from the PDFs):

```bash
python evaluate_dossier.py APP_001
```

It checks: facts (GPA, SAT, major, …), AP courses and exam scores, every
activity's years and hours, awards, recommenders, supplement questions,
whether each citation's quote is on the cited page, and restricted-data leaks.
It ends with a scorecard:

```
SCORECARD
  Facts correct              8/8
  AP courses (transcript)    2/5
  ...
  Citations grounded         29/29
  Restricted data leaks      0
```

Compare your results with the reference run in `results/RESULTS.md`.

---

## 6. Read the dossier

**As a file:** `results/APP_001_dossier.json`. It has two parts: `run` (status,
documents sent/withheld, policies retrieved, every model call and its checks)
and `applicant_dossier` (the dossier).

**In the database:**

```bash
docker exec -it msa8770-postgres psql -U postgres -d riverview_admissions
```

then, inside `psql`:

```sql
-- the dossier (one row per applicant)
SELECT app_id, holistic_assessment, generated_at, updated_at FROM applicant_dossier;
SELECT jsonb_pretty(academic_profile) FROM applicant_dossier WHERE app_id = 'APP_001';

-- every run, including failures
SELECT id, run_status, attempts, runtime_seconds, created_at FROM dossier_generation_runs ORDER BY id;

-- step-by-step audit trail
SELECT created_at, event, details FROM summary_audit_log WHERE app_id = 'APP_001' ORDER BY id;
```

Type `\q` to leave `psql`.

**Dossier fields** (team `applicant_dossier` schema):

| Field | Written by | Contents |
|---|---|---|
| `applicant_demographics` | code (applicant record) | name, school, country/region, major, admission year/term. **No** gender, ethnicity, or contact data. |
| `academic_profile` | model (5a) | facts read from the documents, AP courses and exam scores, rigor, grade patterns, strengths, concerns, evidence |
| `engagement_profile` | model (5b) | every activity (role, years, hours/week), awards, themes, evidence |
| `recommendation_profile` | model (5c) | each recommender (name, role, relationship, observations), common themes, evidence |
| `supplemental_essay_profile` | model (5d) | each supplement question and a summary of the answer, themes, evidence |
| `policy_assessment` | model (5e, RAG) | each retrieved policy: criterion, alignment, findings, evidence |
| `strengths` | model (5f) | main strengths across sections, each with evidence |
| `review_notes` | model (5a–5d) | things the model could not read clearly or found missing |
| `holistic_assessment` | model (5f) | one-paragraph overall summary; never a decision |
| `evidence_map` | code | every citation: section, document, page, quote |
| `generated_at`, `updated_at` | code | first generated / last regenerated |

Every **evidence** item is a document filename, a page number, and a short
quote copied from that page. Code has already checked that each quote is on
that page.

---

## 7. Stop everything

1. In the MinIO Terminal window, press `Ctrl+C`.
2. Stop PostgreSQL:

```bash
docker stop msa8770-postgres
```

3. Leave the Python environment: `deactivate`.

Your data is kept: MinIO's files are in `minio-data/`, and the database is kept
inside the Docker container. Start them again with section 4.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `could not connect to server` / `Connection refused ... 5432` | Open Docker Desktop, then `docker start msa8770-postgres` |
| `extension "vector" is not available` (setup 3) | The container isn't the pgvector image; redo section 3.4 |
| `Connection refused ... 9000` | Start MinIO (section 4.3) |
| `MinIO bucket 'applicant-documents' does not exist` | Run `python setup/1_create_simulated_minio.py` |
| `relation "simulated_applicant_data" does not exist` | Run `python setup/2_create_simulated_postgres.py` |
| `No policies retrieved` | Run `python setup/3_create_policy_store.py` |
| `Not COMPLETE. Skipped` | The applicant already has a dossier; add `--force` |
| `model "qwen3-vl:8b-instruct" not found` | `ollama pull qwen3-vl:8b-instruct` |
| `model "nomic-embed-text" not found` | `ollama pull nomic-embed-text` |
| Ollama connection error | Open the Ollama app |
| Very slow (sections take 5+ minutes each) | Quit Chrome and other apps; check memory in Activity Monitor |
| A section hits the token cap | Rerun with `--force`; if it repeats, the model is looping on that section |
| `ModuleNotFoundError` | Activate the environment: `source .venv/bin/activate` |
| `address already in use` when starting MinIO | MinIO is already running somewhere; use that window or close it |
