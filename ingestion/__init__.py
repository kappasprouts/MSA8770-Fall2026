"""Ingestion module providing FastAPI application, batch ingestor, pipeline runner, and APScheduler setup."""

from ingestion.app import app
from ingestion.batch_ingest import BatchIngestor, IngestedApplication, IngestedDocument
from ingestion.pipeline import BatchIngestionPipeline
from ingestion.scheduler import (
    get_latest_batch_summary,
    init_scheduler,
    run_overnight_batch,
    shutdown_scheduler,
    start_scheduler,
)
from ingestion.test_score_ingest import (
    ScoreIngestResult,
    TestScoreIngestor,
    re_evaluate_applicant,
)

__all__ = [
    "app",
    "BatchIngestor",
    "IngestedApplication",
    "IngestedDocument",
    "BatchIngestionPipeline",
    "init_scheduler",
    "start_scheduler",
    "shutdown_scheduler",
    "run_overnight_batch",
    "get_latest_batch_summary",
    "TestScoreIngestor",
    "ScoreIngestResult",
    "re_evaluate_applicant",
]
