"""Package the measurements, workbook, and benchmark helpers for team review."""
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parents[2]
data = Path(sys.argv[1]).resolve()
destination = root / "outputs" / data.name / "baseline_measurements.zip"
book = destination.parent / "cost_baseline.xlsx"
assert book.is_file()
with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    archive.write(book, "cost_baseline.xlsx")
    for path in sorted(data.rglob("*")):
        if path.is_file():
            archive.write(path, "measurements/" + path.relative_to(data).as_posix())
    for path in sorted(Path(__file__).parent.iterdir()):
        if path.is_file() and path.suffix in {".py", ".ps1", ".mjs", ".md"}:
            archive.write(path, "benchmark_helpers/" + path.name)
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    print(f"{destination}\n{len(archive.namelist())} files; {destination.stat().st_size:,} bytes")
