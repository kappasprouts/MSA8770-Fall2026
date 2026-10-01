"""FastAPI application for admissions batch ingestion and webhook control.

Provides endpoints to trigger, inspect, and monitor autonomous batch ingestion runs,
and hooks into APScheduler for overnight scheduling.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, status
    from fastapi.responses import JSONResponse
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from ingestion.pipeline import BatchIngestionPipeline
from ingestion.scheduler import (
    get_latest_batch_summary,
    init_scheduler,
    run_overnight_batch,
    shutdown_scheduler,
    start_scheduler,
)


@asynccontextmanager
async def lifespan(app: Any):
    """Manage application startup and shutdown lifecycle hooks."""
    logger.info("Starting up Admissions Ingestion Service...")
    init_scheduler()
    start_scheduler()
    yield
    logger.info("Shutting down Admissions Ingestion Service...")
    shutdown_scheduler()


if FASTAPI_AVAILABLE:
    app = FastAPI(
        title="Riverview Admissions Batch Ingestion API",
        description="Ingestion service and validation gate for Riverview State University Admissions Architecture Section 4.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/")
    def root() -> Dict[str, Any]:
        """Root service status and system architecture metadata."""
        return {
            "service": "Riverview Admissions Ingestion Service",
            "architecture_reference": "Section 4: Architecture Plan",
            "trust_boundary_1": "Enforced (MIME, size limits, and manifest completeness)",
            "status": "OPERATIONAL",
        }

    @app.get("/health")
    def health_check() -> Dict[str, Any]:
        """Service health check endpoint."""
        return {
            "status": "healthy",
            "service": "ingestion",
            "scheduler_available": True,
        }

    @app.post("/ingestion/batch/trigger")
    def trigger_batch(
        background_tasks: BackgroundTasks,
        max_packets: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Trigger an on-demand batch ingestion run across drop zone folders."""
        pipeline = BatchIngestionPipeline()
        summary = pipeline.run_batch(max_packets=max_packets)
        return summary

    @app.get("/ingestion/batch/status")
    def batch_status() -> Dict[str, Any]:
        """Retrieve metrics and summary from the most recent batch run."""
        summary = get_latest_batch_summary()
        if summary is None:
            return {"status": "NO_PREVIOUS_RUN", "message": "No batch run has been executed yet."}
        return summary

    @app.post("/ingestion/packet/{applicant_id}")
    def ingest_single_packet(applicant_id: str) -> Dict[str, Any]:
        """Manually trigger ingestion and validation for a specific applicant packet."""
        pipeline = BatchIngestionPipeline()
        packet_dir = pipeline.source_dir / applicant_id
        if not packet_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Applicant packet directory '{applicant_id}' not found in source feed.",
            )

        result = pipeline.process_packet(packet_dir, applicant_id)
        return result

else:
    # Lightweight fallback representation if FastAPI is not yet installed in runtime
    class FallbackApp:
        title = "Riverview Admissions Batch Ingestion Service (FastAPI not installed)"

        def __call__(self, *args, **kwargs):
            raise RuntimeError(
                "FastAPI is not installed. Please install dependencies via: pip install -r requirements.txt"
            )

    app = FallbackApp()
