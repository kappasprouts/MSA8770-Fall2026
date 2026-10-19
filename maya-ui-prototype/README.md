# RiverView State Admissions Review UI

This folder contains the admissions-officer interface for the **AI-Assisted College Admissions Process** prototype developed for MSA 8770. The interface presents validated applicant dossiers, original source documents, policy guidance, grounded officer Q&A, and a simulated human review step.

The AI output is advisory. A human admissions officer remains responsible for every admissions decision.

## What the UI provides

- Applicant queue for dossiers ready for human review
- Plain-language applicant overview
- Academic, engagement, recommendation, and supplemental summaries
- Grounded Officer Q&A based only on the stored applicant dossier
- Officer action workspace for simulated review handoff
- Original PDF document list and embedded document preview
- Policy guidance and supporting evidence
- Separate IT Admin view with model, runtime, policy-retrieval, and validation details

## Implemented workflow

1. The ingestion pipeline receives synthetic applicant records and PDFs.
2. It validates document completeness and routes eligible applicants to `READY_FOR_REVIEW`.
3. Applicant metadata is stored in PostgreSQL, while PDFs are stored in MinIO.
4. The summarizing agent retrieves permitted documents and applicable policies.
5. The model creates dossier sections that are checked by deterministic validation code.
6. The UI reads the validated dossier and supporting metadata from PostgreSQL.
7. Admissions officers review the summary, inspect source PDFs, ask grounded questions, and simulate a human action.

Personal statements and restricted Common App information are presented for authorized human review but are excluded from AI analysis according to the prototype policy.

## Technology

- Next.js and React
- TypeScript
- PostgreSQL with JSONB fields
- MinIO object storage
- GSU-hosted Ollama-compatible model endpoint
- Python ingestion and summarization services maintained elsewhere in the repository

## Prerequisites

Install the following before running the UI:

- Node.js and npm
- Docker Desktop
- PostgreSQL container named `riverview-postgres`
- MinIO container named `riverview-minio`
- A valid GSU Ollama API key
- At least one applicant dossier in the `applicant_dossier` table

## Environment configuration

Create a file named `.env.local` in this directory:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=riverview_admissions
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=applicant-documents

OLLAMA_CHAT_URL=https://gpu-01.insight.gsu.edu:11443/api/chat
OLLAMA_MODEL=gemma3:latest
OLLAMA_API_KEY=PASTE_YOUR_CURRENT_KEY_HERE
```

Never commit `.env.local`, API keys, passwords, or other credentials. The repository's ignore rules should exclude this file.

## Install and run

From PowerShell:

```powershell
cd C:\msa8770project\MSA8770-Fall2026\maya-ui-prototype
npm install
npm run dev -- --port 3002
```

Open:

```text
http://localhost:3002
```

To stop the development server, press `Ctrl+C` in its terminal.

## Verify supporting services

Confirm PostgreSQL and MinIO are running:

```powershell
docker ps
```

Expected containers:

- `riverview-postgres`
- `riverview-minio`

Confirm that a dossier exists:

```powershell
docker exec riverview-postgres `
  psql -U postgres -d riverview_admissions `
  -c "SELECT app_id, generated_at, updated_at FROM applicant_dossier ORDER BY app_id;"
```

Confirm that applicant document metadata exists:

```powershell
docker exec riverview-postgres `
  psql -U postgres -d riverview_admissions `
  -c "SELECT app_id, jsonb_array_length(documents) AS document_count FROM applicants ORDER BY app_id;"
```

## Test the UI

### Applicant and dossier API

```powershell
$response = Invoke-RestMethod `
  "http://localhost:3002/api/dossier?appId=APP_001"

$response.documents.Count
$response.documents | Format-Table file,label,access
```

For the current `APP_001` test packet, the expected document count is `10`.

### Source documents

Open the **Documents** tab and verify that:

- The source-document count is correct.
- Selecting a document loads its PDF preview.
- `Open full PDF` opens the original document.
- Human-only files are labeled separately from AI-analyzed files.

### Grounded Officer Q&A

Example supported question:

```text
What are this applicant's GPA and standardized test scores?
```

Example unsupported question:

```text
What is this applicant's favorite food?
```

The second question should produce a clear statement that the dossier does not contain the requested information. The chatbot should not invent an answer or make an admissions decision.

### IT Admin view

Switch to **IT Admin View** and verify that the UI displays the available:

- Model and run status
- Processing time and attempts
- Retrieved policy identifiers
- Documents sent to and withheld from the model
- Validation results and failure information

## Validation commands

Run these before committing UI changes:

```powershell
npm run lint
npm run build
```

## Important data behavior

The current ingestion implementation stores document metadata in the PostgreSQL `applicants.documents` JSONB array. The UI reads:

- `filename`
- `doc_type`
- `minio_key`
- document readability and error metadata when available

Some ingested records do not contain an `exists` property. The UI therefore includes a document unless `exists` is explicitly `false`.

## Troubleshooting

### The UI displays zero source documents

1. Confirm `applicants.documents` contains an array for the selected applicant.
2. Confirm each object contains `filename` and `minio_key`.
3. Confirm the UI filter uses `document.exists !== false` rather than requiring `document.exists === true`.
4. Restart the Next.js development server and request the dossier API again.

### The PDF list appears but previews fail

Confirm that MinIO is running and that `.env.local` contains the correct bucket. Check which bucket contains the applicant objects:

```powershell
python -c "from minio import Minio; c=Minio('localhost:9000', access_key='minioadmin', secret_key='minioadmin', secure=False); [print(b.name, [o.object_name for o in c.list_objects(b.name, prefix='APP_001/', recursive=True)]) for b in c.list_buckets()]"
```

### Officer Q&A tries to use localhost port 11434

The UI did not load the GSU model configuration. Confirm `.env.local` contains:

```env
OLLAMA_CHAT_URL=https://gpu-01.insight.gsu.edu:11443/api/chat
```

Stop and restart the Next.js server after changing `.env.local`.

### Port 3002 is already in use

```powershell
$nextPid = Get-NetTCPConnection -LocalPort 3002 -State Listen |
  Select-Object -ExpandProperty OwningProcess -Unique

Stop-Process -Id $nextPid -Force
npm run dev -- --port 3002
```

### The summarizer returns `HUMAN_REVIEW_AI_FAILED`

This means a generated section failed deterministic validation after its allowed retry. The run should stop and route the case for human review. This is an implemented safety and failure-handling path, not necessarily an infrastructure failure.

## Prototype limitations

- Officer actions are simulated and are not yet persisted as final admissions decisions.
- Authentication and role-based access are planned but not implemented in this prototype.
- The applicant queue currently focuses on records with generated dossiers.
- External Common App and College Board integrations are simulated.
- The system uses entirely synthetic applicant information for academic testing.

## Human-in-the-loop safeguard

The interface must never automatically admit, waitlist, or reject an applicant. Model summaries and classifications support review, while the admissions officer inspects the evidence and retains final authority.

