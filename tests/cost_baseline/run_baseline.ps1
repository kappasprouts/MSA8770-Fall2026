param([string]$OutputDirectory = "output/cost_baseline_20261021", [switch]$ContinueChat, [int]$OldUiPid = 0)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "../.."))
. ./tests/live_test_setup/settings.ps1
$env:POSTGRES_HOST = "127.0.0.1"
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:25432/rsu_live_test?connect_timeout=5"
$env:MINIO_ENDPOINT = "127.0.0.1:29000"
$env:POSTGRES_CONNECTION_TIMEOUT = "5"
$env:NEXT_TELEMETRY_DISABLED = "1"
if ($ContinueChat) {
    & ./.venv/Scripts/python.exe ./tests/cost_baseline/continue_chat.py --output $OutputDirectory --old-ui-pid $OldUiPid
} else {
    & ./.venv/Scripts/python.exe ./tests/cost_baseline/run_baseline.py --output $OutputDirectory
}
exit $LASTEXITCODE
