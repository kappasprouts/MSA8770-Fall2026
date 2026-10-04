#!/usr/bin/env bash
set -e

echo "=== Running Admissions Ingestion & Completeness Check ==="

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
