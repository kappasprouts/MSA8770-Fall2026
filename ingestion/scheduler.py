"""APScheduler setup for overnight two-pass ingestion and manifest validation."""

from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, Optional

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
    """Execute scheduled overnight batch ingestion run."""
    logger.info("Executing scheduled overnight batch ingestion run...")
    pipeline = BatchIngestionPipeline()
    summary = pipeline.run_batch()
    record_batch_summary(summary)
    logger.info(
        f"Overnight batch run finished. Processed: {summary.get('total_packets_discovered', 0)} packets. "
        f"Breakdown: {summary.get('status_breakdown')}"
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
