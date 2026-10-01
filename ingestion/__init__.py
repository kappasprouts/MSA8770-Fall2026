"""Ingestion module providing FastAPI application, pipeline runner, and APScheduler setup."""

from ingestion.app import app
from ingestion.pipeline import BatchIngestionPipeline
from ingestion.scheduler import (
    get_latest_batch_summary,
    init_scheduler,
    run_overnight_batch,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "app",
    "BatchIngestionPipeline",
    "init_scheduler",
    "start_scheduler",
    "shutdown_scheduler",
    "run_overnight_batch",
    "get_latest_batch_summary",
]
