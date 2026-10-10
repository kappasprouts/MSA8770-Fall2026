# Riverview State University — Applicant Review Chat

A read-only Next.js interface for reviewing completed undergraduate admissions dossiers, viewing original applicant PDFs, and asking evidence-grounded follow-up questions through a local Ollama model.

The UI supports human review; **it does not issue, recommend, or record admission decisions**. Dossiers are generated upstream by the Summarizing Agent pipeline. The Q&A assistant uses the selected applicant's stored dossier as its context, not direct analysis of the PDFs.

![Applicant Review Chat screenshot](public/readme-screenshot.png)

## Contents

1. [Requirements](#requirements)
2. [One-time setup](#one-time-setup)
3. [Run the UI](#run-the-ui)
4. [Using the interface](#using-the-interface)
5. [Data flow and implementation](#data-flow-and-implementation)
6. [Testing checklist](#testing-checklist)
7. [Troubleshooting](#troubleshooting)
8. [Limitations](#limitations)

## Requirements

- **Node.js 20 or newer** and npm.
- **Docker** with the project's PostgreSQL and MinIO services available. In the tested local environment the containers are `eaos-postgres` and `eaos-minio`.
- **Ollama** running locally with `qwen3-vl:8b-instruct` installed.
- A populated PostgreSQL database (`riverview_admissions` in the tested environment) with generated dossier records and applicant document metadata.
- Original PDF objects uploaded to the configured MinIO bucket (`admissions-raw-docs` in the tested environment).

The UI does not ingest applicants, upload documents, generate dossiers, or seed databases. Those are responsibilities of the upstream pipeline.

## One-time setup

From the **repository root**:

```bash
cd ui
npm install
cp .env.local.example .env.local
```

Review `.env.local` and ensure the values match the services actually running on your computer. The following are the important settings (examples only; use the values appropriate to your environment):

```dotenv
OLLAMA_CHAT_URL=http://localhost:11434/api/chat
OLLAMA_MODEL=qwen3-vl:8b-instruct
MINIO_ENDPOINT=localhost:9000
MINIO_BUCKET=admissions-raw-docs
```

Also configure the `POSTGRES_*` connection settings and MinIO access credentials using the variable names in `.env.local.example`. The database name in the tested environment is `riverview_admissions`. **Do not commit `.env.local` or real credentials.** Keep `.env.local.example` free of secrets.

If `npm ci` fails because the lockfile is out of sync, run `npm install` to synchronize dependencies and the lockfile, then include the updated `package-lock.json` in the reviewed commit. For repeatable installs after synchronization, prefer `npm ci`.

## Run the UI

Start Docker Desktop and ensure the project's database and object-storage containers are running:

```bash
docker ps
# If these existing containers are stopped:
docker start eaos-postgres eaos-minio
```

Check Ollama and the required model:

```bash
ollama list
curl http://localhost:11434/api/tags
```

If Ollama is not running, start it using your local Ollama installation (for a terminal-managed instance, `ollama serve`). Do not start a second server if one is already listening on port 11434.

From `ui`:

```bash
npm run dev
```

Open <http://localhost:3000> in a browser. Stop the development server with **Ctrl+C**. To use a different port:

```bash
npm run dev -- --port 3001
```

Before merging changes, verify the production build:

```bash
npm run build
```

## Using the interface

1. **Select an applicant** from the dropdown. Available IDs are read from `applicant_dossier`; an applicant must have a generated dossier to appear.
2. **Applicant Dossier (left):** review applicant information, **Summary**, policy/validation checks, and supporting evidence. Expand cards as needed.
3. **Original Documents (right):** browse the applicant's PDFs. Use **View Full** to open a document separately. The interface can mark documents as withheld from model processing based on saved generation-run metadata. *Withheld from the Summarizing Agent* does not mean hidden from the human reviewer.
4. **Q&A Assistant (bottom):** ask questions about the selected applicant's dossier. The assistant is instructed to answer only from the available dossier evidence and not to make an admissions decision. The conversation panel scrolls vertically.

Example question:

> What do the recommendation letters say about this applicant's leadership? Cite the supporting evidence in the dossier.

The assistant may lack information present only in an original PDF if that information was not included in the saved dossier. Review original documents yourself when needed.

## Data flow and implementation

| Component | Source / responsibility |
|---|---|
| `src/lib/dossier.ts` | PostgreSQL connection and dossier/document retrieval helpers |
| `applicant_dossier` | Saved applicant dossier content |
| `dossier_generation_runs` | Generation-run metadata, including document handling information |
| `applicants.documents` | JSONB array of document metadata, including `filename`, `doc_type`, `minio_key`, and `minio_bucket` |
| MinIO `admissions-raw-docs` | Original PDF objects; keys resemble `APP_013/transcript.pdf` |
| `src/app/api/applicants` | Applicant dropdown data |
| `src/app/api/dossier` | Selected dossier and document listing |
| `src/app/api/documents` | Authorized lookup and streaming of a selected PDF from MinIO |
| `src/app/api/chat` | Dossier-grounded system prompt, Ollama request, and response |
| `src/components/` | UI panels, cards, and chat interface |
| `src/app/globals.css` | UI styling and theme variables |

### Document metadata compatibility

The current ingestion pipeline stores original-document metadata in `applicants.documents`, **not** the older `simulated_applicant_data` table. The UI reads this JSONB array and maps each entry's `minio_key` to the internal `object_key` used by its document-serving helpers. The actual bucket in the tested environment is `admissions-raw-docs`.

Example document entry (illustrative):

```json
{
  "doc_type": "transcript",
  "filename": "transcript.pdf",
  "minio_key": "APP_013/transcript.pdf",
  "minio_bucket": "admissions-raw-docs",
  "exists": true,
  "is_readable": true
}
```

### Q&A model behavior

The chat API sends the saved dossier context and conversation to the configured Ollama model. In the locally tested version, generation options were adjusted to:

```typescript
options: {
  num_ctx: 8192,
  num_predict: 2048,
}
```

These values are not guarantees of complete answers; they increase the available context and output budget. Model runtime and memory use depend on local hardware. The server can log Ollama's `done_reason`, `eval_count`, and response length to help diagnose incomplete responses. Avoid logging sensitive dossier text unnecessarily.

## Testing checklist

Before sharing changes with teammates, verify:

- [ ] `npm run build` succeeds.
- [ ] Applicant dropdown loads generated dossiers.
- [ ] Summary and policy/evidence cards display for a selected applicant.
- [ ] Original Documents panel lists PDFs from `applicants.documents`.
- [ ] **View Full** opens a real PDF from MinIO.
- [ ] Q&A assistant answers a dossier-grounded question and does not suggest an admissions decision.
- [ ] Longer answers finish without being cut off; check Ollama logs if they do not.
- [ ] Switching applicants does not carry over the previous applicant's chat context.
- [ ] `.env.local`, `.next/`, and `node_modules/` are not tracked by Git.

## Troubleshooting

**No applicants in the dropdown:** Confirm PostgreSQL is running and `applicant_dossier` has rows. The UI does not create dossiers.

**Original Documents panel is empty:** Confirm the selected applicant has a nonempty `applicants.documents` JSONB array. The `document_records` table is not the document-list source in this integrated UI.

**Document appears but PDF fails to open:** Check that MinIO is running, `MINIO_BUCKET` is set to `admissions-raw-docs` (or the bucket actually used by your pipeline), and the stored `minio_key` exists in that bucket. MinIO's health endpoint alone does not prove a specific object exists.

**Ollama connection error:** Check `OLLAMA_CHAT_URL`, confirm the server is running at `localhost:11434`, and verify the model with `ollama list`.

**Chat answer stops mid-sentence:** Inspect the development-server log for `done_reason` and `eval_count`. `done_reason: "length"` indicates generation or context limits were reached. If it happens after very few output tokens, inspect the dossier prompt size and available context rather than assuming a chat-scroll issue.

**PDF preview is blank:** Use **View Full** to test the underlying PDF; browser embedded-PDF behavior varies.

**Port 3000 is occupied:** Stop the other process or use `npm run dev -- --port 3001`.

**Database collation-version warning:** A warning may appear with the current PostgreSQL container. It is distinct from the UI's document lookup; do not change database collation or rebuild indexes as part of UI setup without a separate database maintenance plan.

## Limitations

- Prototype UI; not an authenticated production admissions system.
- Read-only; it does not approve, decline, waitlist, or save final decisions.
- Chat responses are model-generated and require human verification against dossier evidence and original PDFs.
- The chat uses the stored dossier context, not arbitrary direct retrieval across the original PDF files.
- Local Docker and Ollama services must be running; performance depends on available machine resources.
- This README documents the integrated local setup tested with the current database and MinIO configuration. Teammates should confirm their container names, credentials, and environment variables before running.
