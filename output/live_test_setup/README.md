# Live integration test from the beginning (Windows / PowerShell)

Start with the repository already present at `D:\Users\miwi\git\MSA8770-Fall2026`. This walkthrough starts new PostgreSQL/pgvector and MinIO test services, downloads the two Ollama models, ingests the supplied synthetic Batch 02, generates APP_012, and opens the review UI.

The Compose project is `rsu-live-test`. PostgreSQL uses host port **25432**, MinIO API **29000**, and the optional MinIO console **29001**. The UI will use **3001**. Ollama uses the existing Windows server on **11434**. The database is **rsu_live_test** and the MinIO bucket is **admissions-raw-docs**. Test data persists in this project's own Docker volumes. The full agent run writes its normal local snapshot under `summarizing_agent/results/`.

Application source is unchanged. The Compose configuration and PowerShell syntax were checked locally. The existing local image `quay.io/minio/aistor/minio:latest` was used. After correcting the license mount, live PostgreSQL/MinIO ingestion of Batch 02 succeeded: 10 applicants, 49 stored PDFs, 7 ready, 1 awaiting materials, and 2 incomplete. APP_012's downloaded transcript matched the source fixture's SHA-256 and opened as a two-page PDF. After setting Python's redirected output to UTF-8, the live Qwen academic test also completed: 4 pages, 1 attempt, 112.5 seconds of inference, 8 evidence items, no reported validation errors, and the expected GPA/SAT/ACT values. See `service_verification.json`, `academic_verification.json`, `TEST_RESULTS.md`, and `ingestion_report.txt` in this directory. The generated narrative says 12 AP courses while the course list contains 11 entries; schema/citation validation does not establish complete factual accuracy. The subsequent user-executed full APP_012 run reported DOSSIER_READY, six validated sections, 88 checked citations, and 520.3 seconds total; the UI also served the dossier, documents, and a chat response. See [TEST_RESULTS.md](TEST_RESULTS.md) for scope and limitations. All test services were stopped afterward.

Run commands one block at a time. If a block fails, resolve that failure before continuing.

**1. Check the prerequisites**

Open Docker Desktop and wait until the engine is running. Use Linux containers. Docker Desktop includes Compose: [official installation documentation](https://docs.docker.com/compose/install/).

Open PowerShell and run:

```powershell
Set-Location D:\Users\miwi\git\MSA8770-Fall2026
python --version
docker version
docker compose version
ollama --version
node --version
```

The repository requires Python 3.10 or newer. The current UI requires Node.js 20.9 or newer. Python, Docker CLI, Ollama, and Node were found on this computer during preparation. For the UI, a normal Node installation also provides npm; [download Node](https://nodejs.org/en/download) if needed. The bundled Node exposed in Codex does not include npm, but the existing UI dependencies can be used directly in step 10.

Ollama's Windows app normally runs in the background on `http://localhost:11434`: [official Windows documentation](https://docs.ollama.com/windows).

**2. Prepare Python**

Use the existing virtual environment if present. Calling its Python directly avoids needing to activate it.

```powershell
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    python -m venv .venv
}
```

For a fresh environment, install the project requirements and the three extra packages imported by the current agent:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install psycopg2-binary pymupdf python-dotenv
.\.venv\Scripts\python.exe -c "import psycopg2, pymupdf, dotenv, minio; print('Agent dependencies OK')"
```

These packages were already installed in this workspace during the review. If you are using that same environment, you can run only the final import check.

**3. Start the test database and MinIO**

Use the MinIO AIStor image already pulled into Docker: `quay.io/minio/aistor/minio:latest`. There is no source build or additional image download in this setup. The PostgreSQL/pgvector image is also already present locally.

This AIStor edition needs a valid license for S3 uploads and downloads. Your existing license file is **C:\Users\miwi\minio\minio.license**. The Compose file mounts this actual file read-only and passes it to the server. To use a different file, set `MINIO_LICENSE_FILE` to its absolute path and update the settings script consistently. If you do not have a license yet, obtain a free-tier license following [MinIO's AIStor container setup](https://docs.min.io/aistor/installation/container/install/). Merely pulling the image does not activate S3 access; without a license, current AIStor releases can start in offline mode with S3 operations blocked ([official explanation](https://docs.min.io/aistor/installation/linux/install/deploy-aistor-on-ubuntu-server/)).

```powershell
Test-Path 'C:\Users\miwi\minio\minio.license' -PathType Leaf
docker compose -f output/live_test_setup/compose.yaml config --quiet
docker compose -f output/live_test_setup/compose.yaml up -d --pull never
docker compose -f output/live_test_setup/compose.yaml ps
```

The license check must return **True**. The local database image includes pgvector; see [pgvector Docker documentation](https://github.com/pgvector/pgvector#docker).

Use `-PathType Leaf`: a directory named `minio.license` can make a plain `Test-Path` return True even though there is no license file. If the mount path changes after the container was created, apply it by recreating only MinIO:

```powershell
docker compose -f output/live_test_setup/compose.yaml up -d --no-deps --force-recreate --pull never minio
```

This reuses the existing MinIO data volume and does not restart PostgreSQL.

Expect both services to be running and PostgreSQL to become healthy. If startup fails:

```powershell
docker compose -f output/live_test_setup/compose.yaml logs --tail 80 postgres minio
```

If MinIO reports a missing, invalid, or expired license, resolve that before ingestion. A 200 health response does not prove S3 operations are enabled. You can instead use your teammates' already-running MinIO instance, but update `settings.ps1` to its exact endpoint and credentials before proceeding and start only the test PostgreSQL service.

**4. Load the matching settings**

```powershell
. .\output\live_test_setup\settings.ps1
```

The first dot and the following space are intentional: they load the settings into the current terminal. Repeat this in each new terminal before running the backend or UI. No root `.env` or UI `.env.local` needs to be overwritten. Both ingestion's `DATABASE_URL` and the agent/UI's `POSTGRES_*` settings point to the same test database.

The settings also set `PYTHONIOENCODING=utf-8` and `PYTHONUNBUFFERED=1`. This prevents Windows `cp1252` errors when Python prints checkmarks through `Tee-Object`, and shows progress as it happens. If you loaded the settings before these were added, load them again before retrying the academic/full test. See [Python's output encoding setting](https://docs.python.org/3.14/using/cmdline.html#envvar-PYTHONIOENCODING).

If Windows explicitly blocks this local script because of execution policy, use a process-only override in this terminal, then repeat the command:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
. .\output\live_test_setup\settings.ps1
```

**5. Verify the services and models**

```powershell
docker compose -f output/live_test_setup/compose.yaml exec -T postgres pg_isready -U postgres -d rsu_live_test
(Invoke-WebRequest "http://localhost:29000/minio/health/live" -UseBasicParsing -TimeoutSec 10).StatusCode
(Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 10).models.name
```

Expect PostgreSQL to accept connections and MinIO to return **200**. If Ollama refuses the connection, open the Ollama application. Alternatively run `ollama serve` in a separate terminal and leave it running; do this only when there is no server already listening on 11434.

Download missing models:

```powershell
ollama pull qwen3-vl:8b-instruct
ollama pull nomic-embed-text
ollama list
```

The current agent reads `VLM_MODEL`, not the older `LLM_MODEL` variable from the root example. Use the exact Instruct tag. These are the [Qwen model](https://ollama.com/library/qwen3-vl:8b-instruct) and [embedding model](https://ollama.com/library/nomic-embed-text) used by this branch.

Check actual inference, not just installed model names:

```powershell
$qwenProbeBody = @{
    model = $env:VLM_MODEL
    stream = $false
    messages = @(@{ role = "user"; content = "Reply with only: QWEN_OK" })
    options = @{ temperature = 0; num_predict = 32 }
} | ConvertTo-Json -Depth 6

$qwenProbeResult = Invoke-RestMethod -Uri $env:OLLAMA_CHAT_URL `
    -Method Post -ContentType "application/json" `
    -Body $qwenProbeBody -TimeoutSec 900
$qwenProbeResult.message.content
$qwenProbeResult.done

$embeddingProbeBody = @{
    model = $env:EMBED_MODEL
    input = @("search_query: academic rigor and GPA")
} | ConvertTo-Json -Depth 4

$embeddingProbeResult = Invoke-RestMethod -Uri $env:OLLAMA_EMBED_URL `
    -Method Post -ContentType "application/json" `
    -Body $embeddingProbeBody -TimeoutSec 120
$embeddingProbeResult.embeddings[0].Count
```

Expect **QWEN_OK**, **True**, and an embedding dimension of **768**, which the policy table requires. The initial Qwen load may be slow. API references: [chat](https://docs.ollama.com/api/chat), [embedding](https://docs.ollama.com/api/embed).

**6. Ingest the supplied documents into the real test stores**

```powershell
.\.venv\Scripts\python.exe run_ingestion_check.py `
    --input-dir batch_02 `
    --require-postgresql `
    --require-object-storage `
    --output output/live_test_setup/ingestion_report.txt `
    --affected-ids output/live_test_setup/affected_ids.json

Get-Content output/live_test_setup/affected_ids.json
```

The strict flags prevent a successful handoff using simulated MinIO or SQLite. Ingestion creates the applicant tables and the configured bucket automatically. It intentionally stops before the AI stage.

For the unchanged supplied Batch 02, the review observed **10 processed, 7 ready, 1 awaiting materials, 2 incomplete**, with APP_012 ready. Confirm APP_012 is in this run's affected-ID file. The incomplete fixtures are intentional.

Verify the database record:

```powershell
docker compose -f output/live_test_setup/compose.yaml exec -T postgres `
    psql -U postgres -d rsu_live_test -c "SELECT app_id, status, jsonb_array_length(documents) AS documents FROM applicants WHERE app_id = 'APP_012';"
```

Expect **READY_FOR_REVIEW** and **5 documents**. Verify an actual MinIO download matches the source fixture:

```powershell
@'
import hashlib
from pathlib import Path
import pymupdf
from summarizing_agent.summarizing_agent import connect_minio, MINIO_BUCKET

client = connect_minio()
response = client.get_object(MINIO_BUCKET, "APP_012/transcript.pdf")
try:
    downloaded = response.read()
finally:
    response.close()
    response.release_conn()

original = Path("batch_02/APP_012/transcript.pdf").read_bytes()
if hashlib.sha256(downloaded).digest() != hashlib.sha256(original).digest():
    raise RuntimeError("Downloaded PDF differs from the source fixture")
with pymupdf.open(stream=downloaded, filetype="pdf") as document:
    print("Authenticated MinIO download and SHA-256 match OK; pages:", len(document))
'@ | .\.venv\Scripts\python.exe -
```

Expect a matching SHA-256 and **2 pages**. This confirms ingestion uploaded real bytes and the agent's authenticated client can download them.

**7. Initialize the policy vector store**

For the new test database, run:

```powershell
.\.venv\Scripts\python.exe summarizing_agent/create_pgvector_once.py
docker compose -f output/live_test_setup/compose.yaml exec -T postgres `
    psql -U postgres -d rsu_live_test -c "SELECT count(*) AS policies, min(vector_dims(embedding)) AS min_dimensions, max(vector_dims(embedding)) AS max_dimensions FROM policy_chunks;"
```

Expect **21 policies**, with both dimension values **768**. This loader calls live `nomic-embed-text` and creates the pgvector extension. It replaces existing policy rows; initialize this new test database once rather than rerunning it for every applicant. It reads process environment variables, so step 4 matters.

**8. Run the focused live PDF/Qwen test**

```powershell
.\.venv\Scripts\python.exe -m summarizing_agent.tests.test_academic_only `
    2>&1 | Tee-Object output/live_test_setup/academic_run.log
```

This existing test reads APP_012 from PostgreSQL, downloads the permitted PDFs from MinIO, renders page images, and calls Qwen. It does not save a dossier or change applicant status.

Check **4 academic pages**, a meaningful academic summary, **Validation errors: []**, unweighted GPA **3.97**, weighted GPA **4.4**, SAT **1530**, and ACT **35**. Inspect supporting document/page quotations. Allow several minutes depending on hardware.

Image-only evidence may be marked `UNVERIFIED_IMAGE_SOURCE`; manually compare those quotations with the PDF. This academic test uses an empty essay-shingle guard, so it does not exercise all full-agent privacy checks.

**9. Generate and verify a complete dossier**

```powershell
$liveRunStartedAt = [DateTimeOffset]::UtcNow.ToString("o")
.\.venv\Scripts\python.exe summarizing_agent/summarizing_agent.py APP_012 `
    2>&1 | Tee-Object output/live_test_setup/full_run.log
```

Use APP_012 explicitly: the default affected-ID lookup currently does not reliably read the new ingestion artifact. On a new test database APP_012 is ready; to deliberately regenerate a dossier on a later run, add `--force` and capture a new start time.

Check the **new** database run:

```powershell
docker compose -f output/live_test_setup/compose.yaml exec -T postgres `
    psql -U postgres -d rsu_live_test -c "SELECT id, app_id, run_status, validation->>'passed' AS validation_passed, created_at FROM dossier_generation_runs WHERE app_id = 'APP_012' AND created_at >= '$liveRunStartedAt'::timestamptz ORDER BY id DESC LIMIT 1;"

docker compose -f output/live_test_setup/compose.yaml exec -T postgres `
    psql -U postgres -d rsu_live_test -c "SELECT app_id, status FROM applicants WHERE app_id = 'APP_012'; SELECT app_id, updated_at FROM applicant_dossier WHERE app_id = 'APP_012';"

Get-Content summarizing_agent/results/APP_012_dossier.json -Raw |
    ConvertFrom-Json | Select-Object -ExpandProperty run |
    Select-Object run_status, validation
```

Pass requires a run created after the recorded start time with **DOSSIER_READY**, validation **true**, a saved dossier row, and applicant status **DOSSIER_READY**. If no fresh run appears, inspect `full_run.log` and the audit table:

```powershell
docker compose -f output/live_test_setup/compose.yaml exec -T postgres `
    psql -U postgres -d rsu_live_test -c "SELECT event, created_at FROM summary_audit_log WHERE app_id = 'APP_012' ORDER BY id DESC LIMIT 5;"
```

Do not use exit code 0 or an existing JSON snapshot alone as success: the current CLI can catch an error and still exit 0, and a failed regeneration can leave an older local dossier. Validation success also does not prove every generated statement correct. Check numeric facts, citations, and withholding against the original PDFs. A passing APP_012 does not establish success for the remaining applicants; the review found separate rendering problems for APP_013, APP_016, and APP_020.

**10. Open the current review UI (optional)**

Open a second PowerShell terminal and load the same settings:

```powershell
Set-Location D:\Users\miwi\git\MSA8770-Fall2026
. .\output\live_test_setup\settings.ps1
Set-Location chat-ui
```

The current UI is in root **chat-ui**, not `summarizing_agent/chat-ui`. If its dependencies are already installed, start it directly with the available Node executable:

```powershell
& "C:\Users\miwi\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" `
    .\node_modules\next\dist\bin\next dev --hostname 127.0.0.1 --port 3001
```

On this computer, Node is available through Codex's bundled runtime, but `npm.cmd` is not installed/on PATH. The UI dependencies are already present, so use the direct Node executable above and skip `npm.cmd ci` and `npm.cmd run dev`. The absolute executable path also works in a PowerShell terminal where `node` is not on PATH. If a server is already running on port 3001, open its URL rather than starting a second server.

Only for a fresh machine where the UI dependencies are absent, install normal Node/npm first and check `npm.cmd --version` before using these commands:

```powershell
npm.cmd ci
npm.cmd run dev -- --hostname 127.0.0.1 --port 3001
```

Choose either launch path. Leave the server terminal running and open [the test UI](http://localhost:3001). Process environment variables take precedence over `.env.local`, so the settings script supplies the matching database, MinIO bucket, and chat model.

Select APP_012 and check that its dossier loads. Open `transcript.pdf` using **View Full** to prove the UI can retrieve a real PDF from MinIO. Ask: **What is this applicant's unweighted GPA, and what evidence supports it?** Expect **3.97** with supporting evidence. Also test an admissions-decision request and withholding questions; record any inappropriate response as a failure. The code review found guardrail gaps, so these outcomes need testing.

The applicant dropdown contains saved dossiers, not all ingested applicants. An empty dropdown before successful generation is expected. Set `MINIO_BUCKET=admissions-raw-docs` consistently; the UI example's `applicant-documents` default does not match ingestion.

**11. Stop and resume**

Stop the UI with Ctrl+C. From the repository root, stop just these test services:

```powershell
docker compose -f output/live_test_setup/compose.yaml stop
```

To resume later:

```powershell
docker compose -f output/live_test_setup/compose.yaml up -d --pull never
. .\output\live_test_setup\settings.ps1
```

The test volumes retain applicant documents, policy vectors, and dossiers. You do not need to reseed or ingest again to view the previous successful dossier. Reingestion currently resets ready applicant statuses; use it deliberately when testing another ingestion run.
