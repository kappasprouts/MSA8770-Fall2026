"""Record Ollama's observed CPU/GPU processor split during a benchmark."""
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

out = Path(sys.argv[1])
while True:
    try:
        progress = json.loads((out / "progress.json").read_text(encoding="utf-8"))
        if progress["stage"].startswith("finished_"):
            break
        result = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        with (out / "processor_split.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({**progress, "stage_started_at_utc": progress.get("timestamp_utc"), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                "ollama_ps": result.stdout.strip(), "exit_code": result.returncode}) + "\n")
    except Exception as error:
        print(error, flush=True)
    time.sleep(15)
