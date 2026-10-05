#!/usr/bin/env bash
set -e

echo "=== Running Admissions Ingestion & Completeness Check ==="
echo "Pipeline Architecture:"
echo "  - Pass 1: Parse CSV flat file -> Stage explicit 33-column relational schema + JSONB arrays in PostgreSQL"
echo "  - Pass 2: Traverse files -> Verify TB1 perimeter hygiene (%PDF-, size), upload to MinIO ('admissions-raw-docs'), archive orphans"
echo "  - Component 3: Manifest Gate -> 3-way deterministic routing & export affected_ids.json"
echo "  - Hard Stop: Explicit halt prior to downstream Summarizer / LLM Gateway"
echo "--------------------------------------------------------"

# 1. Target directory (defaults to batch_01 if not provided)
INPUT_DIR="${1:-batch_01}"

# 2. Check Python 3 availability
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed or not in PATH."
    exit 1
fi

# 3. Ensure dependencies are satisfied
if [ -f "requirements.txt" ]; then
    python3 -m pip install -q -r requirements.txt
fi

# 4. Execute the hard-stopped ingestion & manifest check
python3 run_ingestion_check.py --input-dir "$INPUT_DIR"

echo "=== Pipeline Completed & Stopped (Halted before downstream Summarizer/VLM) ==="
echo "Ready for downstream Summarizer: See affected_ids.json"
