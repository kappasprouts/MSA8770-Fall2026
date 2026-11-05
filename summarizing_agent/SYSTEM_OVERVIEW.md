# Riverview Admissions — End-to-End System Overview

One AI pipeline, two live PostgreSQL/MinIO stores, two separate review UIs
reading from them. This doc shows how the whole thing fits together and
how to stand it up from zero. For deep detail on any one piece, see the
doc it links to — this is the map, not the territory.

---

## 1. The whole picture

```
 ┌───────────────────────┐        ┌──────────────────────────┐
 │  MinIO                │        │  PostgreSQL               │
 │  bucket:               │        │  (pgvector)                │
 │  applicant-documents    │        │                             │
 │                         │        │  simulated_applicant_data   │◄──┐
 │  APP_001/*.pdf  ───────┼───────►│  (base record + doc keys)   │   │
 │                         │        │                             │   │
 └───────────┬─────────────┘        │  policy_chunks               │   │
             │                      │  (policies.yaml, embedded)    │   │
             │ read by              └──────────────┬───────────────┘   │
             │ summarizing_agent.py                 │ read by          │
             ▼                                      ▼                  │
      ┌─────────────────────────────────────────────────────┐         │
      │          summarizing_agent.py (the "agent")           │        │
      │  PDFs → page images → Qwen3-VL per section            │        │
      │  + RAG policy retrieval → validated dossier            │        │
      └───────────────────────┬─────────────────────────────┘         │
                               │ writes                                │
                               ▼                                       │
      ┌─────────────────────────────────────────────────────┐         │
      │  PostgreSQL                                            │       │
      │  applicant_dossier           (the finished dossier)     │       │
      │  dossier_generation_runs     (run metadata, every run)   │      │
      │  summary_audit_log           (audit trail)                │     │
      └───────────────┬───────────────────────┬─────────────────┘     │
                       │ read live             │ read live             │
                       ▼                       ▼                       │
        ┌───────────────────────┐   ┌───────────────────────────┐     │
        │  app.py (Streamlit)    │   │  chat-ui (Next.js)          │    │
        │  Officer Review Portal │   │  Applicant Review Chat       │   │
        │  :8501                 │   │  :3000                        │  │
        │                        │   │  also streams PDFs from ──────┼──┘
        │                        │   │  MinIO, and calls Ollama      │
        │                        │   │  (qwen3-vl:8b-instruct) for   │
        │                        │   │  the Q&A chatbot               │
        └───────────────────────┘   └───────────────────────────┘
```

**Nothing downstream of PostgreSQL/MinIO touches local files anymore.**
Both UIs read live. (`summarizing_agent.py` *also* writes a local
`results/<APP_ID>_dossier.json` snapshot as a byproduct — that file still
gets created, but neither UI reads it; it's just a convenience artifact.)

---

## 2. The pieces

| Piece | What it is | Reads | Writes |
|---|---|---|---|
| `summarizing_agent.py` | The AI pipeline. One Qwen3-VL call per dossier section, RAG policy retrieval via pgvector, citation-checked, never decides anything. | `simulated_applicant_data`, `policy_chunks`, MinIO PDFs | `applicant_dossier`, `dossier_generation_runs`, `summary_audit_log`, `results/*.json` |
| `evaluate_dossier.py` | Scores a generated dossier against a hand-verified answer key. | `results/*.json`, `answer_keys/*.json` | prints a scorecard |
| `setup/1_create_simulated_minio.py` | Seeds the MinIO bucket with the sample PDFs. | `data/sample_docs/` | MinIO bucket `applicant-documents` |
| `setup/2_create_simulated_postgres.py` | Seeds `simulated_applicant_data` from the sample CSV. | CSV | Postgres |
| `setup/3_create_policy_store.py` | Embeds `data/policies.yaml` for RAG. | `data/policies.yaml` | `policy_chunks` (pgvector) |
| `app.py` | Officer Review Portal — Streamlit. Full workspace: dossier, validation, documents list, policies, and the human officer-action form. | `applicant_dossier`, `dossier_generation_runs` (Postgres, live) | `audit_logs/officer_actions.jsonl` (local — officer decisions aren't part of the DB schema) |
| `chat-ui/` | Applicant Review Chat — Next.js. Dossier + original documents + a grounded Q&A chatbot. | `applicant_dossier`, `dossier_generation_runs`, `simulated_applicant_data` (Postgres, live) + MinIO (PDF bytes, live) | nothing |

None of the UI code was written by the agent, and the agent was never
modified to build the UIs — they're separate layers reading its output.

---

## 3. Running everything from zero

Follow in order. Each step links to the doc with full detail.

1. **Install prerequisites** — Docker, Python, MinIO, Ollama, the Python
   venv. See [`README.md`](README.md) section 3 ("One-time setup").
2. **Start Postgres and MinIO**:
   ```bash
   docker start msa8770-postgres   # or the `docker run` command in README.md §3.4 if it doesn't exist yet
   cd rag_agent
   MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin \
     minio server ./minio-data --address :9000 --console-address :9001
   ```
3. **Seed them** (only needed once, or after a reset) — see
   [`README.md`](README.md) section 5.1:
   ```bash
   python setup/1_create_simulated_minio.py
   python setup/2_create_simulated_postgres.py
   python setup/3_create_policy_store.py
   ```
4. **Run the agent** for an applicant — see
   [`README.md`](README.md) section 5.3:
   ```bash
   python summarizing_agent.py APP_001
   ```
   This writes the dossier into `applicant_dossier`. Takes ~10 minutes.
5. **Launch both UIs**:
   ```bash
   ollama serve                       # terminal A
   streamlit run app.py               # terminal B → localhost:8501
   cd chat-ui && npm install && npm run dev   # terminal C → localhost:3000
   ```
6. **Test it** — work through
   [`TESTING_GUIDE.md`](TESTING_GUIDE.md), which has a pass/fail checklist
   for both UIs, including what should happen if Postgres, MinIO, or
   Ollama go down.

If you already have Postgres/MinIO populated (check with
`SELECT app_id FROM applicant_dossier;`), skip straight to step 5.

---

## 4. Where to look for more detail

- **The pipeline itself** (how the agent works, what it withholds, how
  citations are validated): [`README.md`](README.md)
- **The chat app** (architecture, env vars, troubleshooting):
  [`chat-ui/README.md`](chat-ui/README.md)
- **Testing both UIs** (step-by-step checks with pass/fail criteria):
  [`TESTING_GUIDE.md`](TESTING_GUIDE.md)
