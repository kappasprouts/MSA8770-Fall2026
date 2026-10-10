"""API and scheduler adapter for the canonical two-pass ingestion runner.

The ingestion boundary ends after document linking and the deterministic manifest
gate. The affected IDs artifact is the handoff to the future summarizing agent;
this module does not parse document text or invoke a model.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from storage.storage_manager import StorageManager, normalize_applicant_id


# The API and APScheduler may share configured artifact paths in a process.
_RUN_LOCK = Lock()


class BatchIngestionPipeline:
    """Run the same ingestion, manifest gate, and hard stop used by the CLI."""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        config_path: Optional[Path] = None,
        report_path: Optional[Path] = None,
        affected_ids_path: Optional[Path] = None,
        storage_manager: Optional[StorageManager] = None,
        require_object_storage: Optional[bool] = None,
        require_postgresql: Optional[bool] = None,
    ) -> None:
        root = Path(__file__).resolve().parent.parent
        self.source_dir = Path(source_dir or os.getenv("INGESTION_INPUT_DIR", root / "data/batches/batch_01"))
        self.config_path = Path(config_path or os.getenv("INGESTION_CONFIG_PATH", root / "policy/ingestion_rules.yaml"))
        configured_report = report_path or os.getenv("INGESTION_REPORT_PATH")
        configured_ids = affected_ids_path or os.getenv("INGESTION_AFFECTED_IDS_PATH")
        
        batch_name = self.source_dir.name
        self.report_path = Path(
            configured_report or root / "output/ingestion" / f"ingestion_{batch_name}_report.txt"
        )
        self.affected_ids_path = Path(configured_ids or root / "output/ingestion/affected_ids.json")
        self.storage_manager = storage_manager
        self.require_object_storage = (
            require_object_storage
            if require_object_storage is not None
            else os.getenv("INGESTION_REQUIRE_OBJECT_STORAGE", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.require_postgresql = (
            require_postgresql
            if require_postgresql is not None
            else os.getenv("INGESTION_REQUIRE_POSTGRESQL", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )

    @staticmethod
    def _storage_mode(storage: StorageManager) -> str:
        if not getattr(storage, "db_available", False):
            return "dry_run"
        if getattr(storage, "is_sqlite_fallback", False):
            return "sqlite_fallback"
        if str(getattr(storage, "database_url", "")).startswith("sqlite"):
            return "sqlite"
        return "postgresql"

    @staticmethod
    def _applicant_result(routed: Any) -> Dict[str, Any]:
        findings = routed.missing_documents + routed.missing_fields + routed.errors
        return {
            "applicant_id": routed.applicant_id,
            "status": routed.status.value,
            "is_valid": routed.is_valid,
            "routing_destination": routed.routing_destination,
            "findings_count": len(findings),
            "missing_documents": list(routed.missing_documents),
            "missing_fields": list(routed.missing_fields),
            "errors": list(routed.errors),
            "total_documents": routed.total_documents,
            "documents_parsed": 0,
            "ai_evaluated": False,
        }

    @staticmethod
    def _run_artifact_path(base: Path, run_id: str, label: Optional[str]) -> Path:
        suffix = f"_{label}_{run_id}" if label else f"_{run_id}"
        return base.with_name(f"{base.stem}{suffix}{base.suffix}")

    def run_batch(
        self,
        max_packets: Optional[int] = None,
        *,
        applicant_ids: Optional[Iterable[str]] = None,
        report_path: Optional[Path] = None,
        affected_ids_path: Optional[Path] = None,
        artifact_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a batch and export its ready IDs, stopping before AI work.

        ``max_packets`` belonged to the former directory-scanning implementation.
        A truncated CSV/document batch is unsafe to stage, so reject this legacy
        option explicitly instead of silently processing a different population.
        """
        if max_packets is not None:
            raise ValueError("max_packets is unsupported for two-pass ingestion; use an applicant ID scope or a separate batch directory")

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
        output_report = Path(report_path) if report_path is not None else self._run_artifact_path(
            self.report_path, run_id, artifact_label
        )
        output_ids = Path(affected_ids_path) if affected_ids_path is not None else self._run_artifact_path(
            self.affected_ids_path, run_id, artifact_label
        )
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_ids.parent.mkdir(parents=True, exist_ok=True)
        storage = self.storage_manager or StorageManager()

        # Import here to keep ingestion package initialization free of a cycle.
        from ingestion.run_ingestion_check import run_pipeline

        with _RUN_LOCK:
            gate_result = run_pipeline(
                input_dir=str(self.source_dir),
                config_file=str(self.config_path),
                report_file=str(output_report),
                affected_ids_file=str(output_ids),
                storage_manager=storage,
                applicant_ids=set(applicant_ids) if applicant_ids is not None else None,
                require_object_storage=self.require_object_storage,
                require_postgresql=self.require_postgresql,
                run_id=run_id,
            )

        results = [self._applicant_result(routed) for routed in gate_result.routed_applicants]
        return {
            "status": "COMPLETED",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "total_packets_discovered": gate_result.total_processed,
            "status_breakdown": {
                "READY_FOR_REVIEW": gate_result.total_valid,
                "AWAITING_MATERIALS": gate_result.total_awaiting_materials,
                "INCOMPLETE": gate_result.total_incomplete,
                "ERROR": gate_result.total_error,
            },
            "results": results,
            "affected_ids": list(gate_result.affected_ids),
            "affected_ids_file": str(output_ids.resolve()),
            "report_file": str(output_report.resolve()),
            "hard_stop": True,
            "storage_mode": self._storage_mode(storage),
            "minio_available": bool(getattr(storage, "minio_available", False)),
            "object_storage_required": self.require_object_storage,
            "postgresql_required": self.require_postgresql,
            "handoff_ready": (
                self.require_postgresql
                and self.require_object_storage
                and self._storage_mode(storage) == "postgresql"
                and bool(getattr(storage, "minio_available", False))
            ),
        }

    def process_packet(self, applicant_id: str) -> Optional[Dict[str, Any]]:
        """Run the canonical gate for one ID and write separate handoff files."""
        if re.fullmatch(r"APP[_\-\s]?\d+", applicant_id, re.IGNORECASE) is None:
            raise ValueError(f"Invalid applicant ID: {applicant_id!r}")
        canonical_id = normalize_applicant_id(applicant_id)
        if canonical_id is None:
            raise ValueError(f"Invalid applicant ID: {applicant_id!r}")

        safe_id = re.sub(r"[^A-Za-z0-9_]", "_", canonical_id)
        summary = self.run_batch(applicant_ids={canonical_id}, artifact_label=safe_id)
        if not summary["results"]:
            return None
        result = dict(summary["results"][0])
        result.update({
            "affected_ids": summary["affected_ids"],
            "affected_ids_file": summary["affected_ids_file"],
            "report_file": summary["report_file"],
            "hard_stop": summary["hard_stop"],
            "storage_mode": summary["storage_mode"],
            "minio_available": summary["minio_available"],
            "object_storage_required": summary["object_storage_required"],
            "postgresql_required": summary["postgresql_required"],
            "handoff_ready": summary["handoff_ready"],
        })
        return result
