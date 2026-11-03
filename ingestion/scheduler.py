"""APScheduler setup for overnight two-pass ingestion and manifest validation."""

from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, Optional
from pathlib import Path
import subprocess
import sys

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

from ingestion.pipeline import BatchIngestionPipeline

logger = logging.getLogger(__name__)

_scheduler = None
_latest_batch_summary: Optional[Dict[str, Any]] = None


def run_overnight_batch() -> Dict[str, Any]:
    """Run overnight ingestion and launch the event consumer."""

    logger.info("Executing scheduled overnight batch ingestion run...")

    pipeline = BatchIngestionPipeline()
    summary = pipeline.run_batch()

    record_batch_summary(summary)

    logger.info(
        "Overnight ingestion finished. Processed: %s packets. Breakdown: %s",
        summary.get("total_packets_discovered", 0),
        summary.get("status_breakdown"),
    )

    if not summary.get("handoff_ready"):
        logger.warning(
            "Event consumer not launched: ingestion handoff is not ready."
        )
        return summary

    if not summary.get("affected_ids"):
        logger.info("No affected applicant IDs; skipping event consumer.")
        return summary

    event_file = Path(summary["affected_ids_file"]).resolve()
    consumer_script = Path(__file__).resolve().parent / "event_consumer.py"

    try:
        process = subprocess.Popen(
            [sys.executable, str(consumer_script), str(event_file)],
            cwd=str(consumer_script.parent.parent),
            start_new_session=True,
        )
        logger.info(
            "Event consumer launched for %s (PID %s)",
            event_file.name,
            process.pid,
        )
    except OSError:
        logger.exception(
            "Failed to launch event consumer for %s. Event file retained for recovery.",
            event_file,
        )

    return summary


def record_batch_summary(summary: Dict[str, Any]) -> None:
    """Publish the latest successful on-demand or overnight run for status reads."""
    global _latest_batch_summary
    _latest_batch_summary = summary


def get_latest_batch_summary() -> Optional[Dict[str, Any]]:
    """Return metrics and outcomes from the most recent batch run."""
    return _latest_batch_summary


def init_scheduler(
    cron_hour: Optional[int] = None,
    cron_minute: Optional[int] = None,
) -> Optional[Any]:
    """Initialize and configure the APScheduler for overnight batch triggers."""
    global _scheduler

    hour = cron_hour if cron_hour is not None else int(os.getenv("BATCH_CRON_HOUR", "2"))
    minute = cron_minute if cron_minute is not None else int(os.getenv("BATCH_CRON_MINUTE", "0"))

    if not APSCHEDULER_AVAILABLE:
        logger.info(
            f"APScheduler library not installed. Mock scheduler initialized for overnight {hour:02d}:{minute:02d}."
        )
        return None

    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            func=run_overnight_batch,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="overnight_admissions_batch_job",
            name="Autonomous Overnight Admissions Batch Ingestion",
            replace_existing=True,
        )
        logger.info(f"Configured APScheduler overnight batch job for {hour:02d}:{minute:02d} UTC.")

    return _scheduler


def start_scheduler() -> None:
    """Start the APScheduler if available."""
    global _scheduler
    if APSCHEDULER_AVAILABLE and _scheduler and not _scheduler.running:
        _scheduler.start()
        logger.info("APScheduler background service started.")
    elif not APSCHEDULER_AVAILABLE:
        logger.info("APScheduler not available; running in manual/API triggered mode.")


def shutdown_scheduler(wait: bool = False) -> None:
    """Shut down the APScheduler gracefully."""
    global _scheduler
    if APSCHEDULER_AVAILABLE and _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=wait)
        logger.info("APScheduler background service shut down.")
