# Dot-source this in every PowerShell terminal used for the test.
# These credentials belong only to the local Compose test services.
# Keep Python's Unicode status messages safe when PowerShell pipes output.
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:25432/rsu_live_test"
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "25432"
$env:POSTGRES_DB = "rsu_live_test"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_PASSWORD = "postgres"

$env:MINIO_ENDPOINT = "localhost:29000"
$env:MINIO_ACCESS_KEY = "minioadmin"
$env:MINIO_SECRET_KEY = "minioadmin"
$env:MINIO_BUCKET = "admissions-raw-docs"
$env:MINIO_SECURE = "false"
$env:MINIO_LICENSE_FILE = "C:/Users/miwi/minio/minio.license"

$env:VLM_MODEL = "qwen3-vl:8b-instruct"
$env:OLLAMA_MODEL = "qwen3-vl:8b-instruct"
$env:EMBED_MODEL = "nomic-embed-text"
$env:OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
$env:OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$env:SQLITE_STORE_PATH = Join-Path $repoRoot "data/local/live_test_fallback.db"
