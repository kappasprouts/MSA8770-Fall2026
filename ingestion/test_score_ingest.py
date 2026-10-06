"""Asynchronous and synchronous delta ingestors for external test scores (College Board SAT/AP and ACT).

Implements Component 2 delta ingestion:
- Parses SAT subscores (Math, EBRW) and AP scores from College Board feeds.
- Parses ACT composite and section scores from ACT feeds.
- Matches incoming student records to ApplicationRecord by email (case-insensitive) or DOB fallback.
- Appends AP scores to ap_test_scores JSONB array without duplicating subject/score pairs.
- Unmatched records are archived to the OrphanTestScore table.
- Re-triggers ManifestValidationGate on matched applicants and writes a separate
  affected-ID handoff for each run when ready applicants receive new scores.
- Operates in live PostgreSQL or in-memory dry-run mode when DB is unavailable.
"""

import asyncio
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from ingestion.batch_ingest import IngestedApplication, IngestedDocument
from storage.models import Applicant, OrphanTestScore
from storage.storage_manager import StorageManager
from validation.manifest_gate import (
    GateRoutingDestination,
    GateStatus,
    ManifestValidationGate,
    RoutedApplicant,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoreIngestResult:
    """Summary of delta test score ingestion run."""
    source: str
    file_path: str
    total_records: int = 0
    matched_count: int = 0
    orphan_count: int = 0
    matched_app_ids: List[str] = field(default_factory=list)
    promoted_app_ids: List[str] = field(default_factory=list)
    affected_ids: List[str] = field(default_factory=list)
    affected_ids_file: Optional[str] = None
    handoff_ready: bool = False
    orphan_identifiers: List[str] = field(default_factory=list)
    orphans: List[OrphanTestScore] = field(default_factory=list)
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "file_path": self.file_path,
            "total_records": self.total_records,
            "matched_count": self.matched_count,
            "orphan_count": self.orphan_count,
            "matched_app_ids": self.matched_app_ids,
            "promoted_app_ids": self.promoted_app_ids,
            "affected_ids": self.affected_ids,
            "affected_ids_file": self.affected_ids_file,
            "handoff_ready": self.handoff_ready,
            "orphan_identifiers": self.orphan_identifiers,
            "executed_at": self.executed_at,
        }


def _normalize_col(name: str) -> str:
    """Normalize a column header for flexible lookup."""
    return re.sub(r"[^a-z0-9]", "_", str(name).strip().lower()).strip("_")


def _get_val_by_aliases(row: Dict[str, Any], aliases: List[str]) -> Optional[str]:
    """Retrieve string value from a dictionary using normalized alias matching."""
    norm_row = {_normalize_col(k): v for k, v in row.items()}
    for alias in aliases:
        norm_alias = _normalize_col(alias)
        if norm_alias in norm_row:
            val = norm_row[norm_alias]
            if val is not None and str(val).strip() != "" and str(val).lower() != "nan":
                return str(val).strip()
    return None


def _parse_int_by_aliases(row: Dict[str, Any], aliases: List[str]) -> Optional[int]:
    """Retrieve integer value from a dictionary using normalized alias matching."""
    val_str = _get_val_by_aliases(row, aliases)
    if val_str is None:
        return None
    try:
        # Handle floats encoded as strings like "750.0"
        return int(round(float(val_str)))
    except (ValueError, TypeError):
        return None


def _is_duplicate_ap(existing_scores: List[Any], subject: str, score: int) -> bool:
    """Check if a subject/score pair already exists in ap_test_scores JSONB array."""
    norm_subj = subject.strip().lower()
    for item in existing_scores:
        if isinstance(item, dict):
            existing_subj = str(item.get("subject", "")).strip().lower()
            try:
                existing_score = int(item.get("score", 0))
            except (ValueError, TypeError):
                existing_score = None
            if existing_subj == norm_subj and existing_score == score:
                return True
        elif isinstance(item, str):
            s_lower = item.strip().lower()
            if norm_subj in s_lower and str(score) in s_lower:
                return True
    return False


def _score_snapshot(app: Applicant) -> Tuple[Any, ...]:
    """Capture fields owned by the score feeds before and after persistence."""
    return (
        app.sat_math,
        app.sat_ebrw,
        app.superscored_sat_score,
        app.act_composite,
        app.superscored_act_score,
        app.act_english,
        app.act_math,
        app.act_reading,
        app.act_science,
        app.act_writing,
        json.dumps(app.ap_test_scores or [], sort_keys=True, default=str),
    )


def applicant_to_ingested(app: Applicant, default_bucket: str = "admissions-raw-docs") -> IngestedApplication:
    """Convert an Applicant ORM/dry-run instance into an IngestedApplication for gate evaluation."""
    docs: List[IngestedDocument] = []
    raw_docs = getattr(app, "documents", []) or []
    for d in raw_docs:
        if isinstance(d, dict):
            docs.append(
                IngestedDocument(
                    filename=d.get("filename", "document.pdf"),
                    file_path=Path(d.get("storage_path") or d.get("filename") or "document.pdf"),
                    doc_type=d.get("doc_type", "other"),
                    file_size_bytes=d.get("file_size", d.get("file_size_bytes", 1024)),
                    mime_type=d.get("mime_type", "application/pdf"),
                    sha256_checksum=d.get("sha256", d.get("sha256_checksum", "0" * 64)),
                    applicant_id=app.app_id,
                    exists=d.get("exists", True),
                    is_readable=d.get("is_readable", True),
                    error_message=d.get("error_message"),
                    minio_key=d.get("minio_key", ""),
                    minio_bucket=d.get("minio_bucket", default_bucket),
                )
            )
        elif isinstance(d, IngestedDocument):
            docs.append(d)

    metadata = {
        "App_ID": app.app_id,
        "First_Name": app.first_name,
        "Last_Name": app.last_name,
        "Date_Of_Birth": app.date_of_birth,
        "Email_Address": app.email_address,
        "Name_of_HS": app.name_of_hs,
        "Intended_Major": app.intended_major,
        "Admission_Year": app.admission_year,
        "Admission_Term": app.admission_term,
        "Superscored_SAT_Score": app.superscored_sat_score,
        "Superscored_ACT_Score": app.superscored_act_score,
        "sat_math": app.sat_math,
        "sat_ebrw": app.sat_ebrw,
        "act_composite": app.act_composite,
        "ap_test_scores": app.ap_test_scores,
    }

    return IngestedApplication(
        applicant_id=app.app_id,
        metadata=metadata,
        activities=list(app.activities or []),
        awards=list(app.awards or []),
        ap_test_scores=list(app.ap_test_scores or []),
        hooks=list(app.hooks or []),
        documents=docs,
        status=app.status,
        routing_destination=app.routing_destination,
    )


def re_evaluate_applicant(
    app_id: str,
    storage_manager: Optional[StorageManager] = None,
    config_path: Optional[Union[str, Path]] = None,
    affected_ids_path: Union[str, Path] = "affected_ids.json",
    gate: Optional[ManifestValidationGate] = None,
) -> Optional[RoutedApplicant]:
    """Re-runs ManifestValidationGate on an applicant who received updated scores.

    Status changes are persisted here. The score ingestor owns the per-run
    affected-ID handoff after it verifies that score persistence succeeded.

    ``affected_ids_path`` remains accepted for callers using the older signature.
    """
    storage = storage_manager or StorageManager()
    applicant = storage.get_applicant(app_id)
    if not applicant:
        logger.warning("re_evaluate_applicant: Applicant '%s' not found.", app_id)
        return None

    prev_status = applicant.status
    validation_gate = gate or ManifestValidationGate(config_path=Path(config_path) if config_path else None)

    ingested_app = applicant_to_ingested(applicant)
    routed = validation_gate.evaluate_applicant(ingested_app)

    # An incomplete packet can become ready after a score feed or a prior gate
    # evaluation that has since become stale.
    if prev_status == "INCOMPLETE" and (
        routed.status == GateStatus.READY_FOR_REVIEW or routed.status == GateStatus.VALID
    ):
        updated = storage.update_applicant_status(
            app_id=app_id,
            status=GateStatus.READY_FOR_REVIEW.value,
            routing_destination=GateRoutingDestination.READY_FOR_REVIEW.value,
        )
        if not updated:
            raise RuntimeError(f"Could not persist manifest status for {app_id}")
        logger.info("Applicant '%s' promoted from INCOMPLETE to READY_FOR_REVIEW.", app_id)
    elif routed.status.value != prev_status:
        updated = storage.update_applicant_status(
            app_id=app_id,
            status=routed.status.value,
            routing_destination=routed.routing_destination,
        )
        if not updated:
            raise RuntimeError(f"Could not persist manifest status for {app_id}")

    return routed


class TestScoreIngestor:
    """Asynchronous and synchronous delta ingestor for College Board and ACT score feeds."""
    __test__ = False

    def __init__(
        self,
        storage_manager: Optional[StorageManager] = None,
        config_path: Optional[Union[str, Path]] = None,
        affected_ids_path: Union[str, Path] = "affected_ids.json",
        require_object_storage: bool = False,
        require_postgresql: bool = False,
    ):
        self.storage_manager = storage_manager or StorageManager()
        self.config_path = Path(config_path) if config_path else Path("config/policies.yaml")
        self.affected_ids_path = Path(affected_ids_path)
        self.require_object_storage = require_object_storage
        self.require_postgresql = require_postgresql
        self.gate = ManifestValidationGate(config_path=self.config_path)

    def _check_storage(self) -> None:
        if self.require_postgresql and (
            not self.storage_manager.db_available or self.storage_manager.is_sqlite_fallback
        ):
            raise RuntimeError("PostgreSQL is unavailable; refusing score handoff")
        if self.require_object_storage and not self.storage_manager.minio_available:
            raise RuntimeError("MinIO is unavailable; refusing score handoff")

    def _new_result(self, source: str, path: Path) -> ScoreIngestResult:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:8]
        base = self.affected_ids_path
        output = base.with_name(f"{base.stem}_{source.lower()}_{run_id}{base.suffix or '.json'}")
        return ScoreIngestResult(
            source=source,
            file_path=str(path),
            affected_ids_file=str(output.resolve()),
            handoff_ready=self.require_postgresql and self.require_object_storage,
        )

    @staticmethod
    def _write_handoff(result: ScoreIngestResult) -> None:
        """Publish one complete handoff artifact without replacing another run's file."""
        output = Path(result.affected_ids_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        try:
            temporary.write_text(json.dumps(result.affected_ids, indent=2), encoding="utf-8")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    def _record_matched_update(
        self,
        result: ScoreIngestResult,
        app: Applicant,
        before: Tuple[Any, ...],
        persisted: Optional[Applicant],
        prev_status: str,
    ) -> None:
        if persisted is None:
            raise RuntimeError(f"Could not persist test scores for {app.app_id}")

        routed = re_evaluate_applicant(
            app_id=app.app_id,
            storage_manager=self.storage_manager,
            config_path=self.config_path,
            gate=self.gate,
        )
        if routed is None:
            raise RuntimeError(f"Could not re-evaluate applicant {app.app_id}")

        result.matched_count += 1
        result.matched_app_ids.append(app.app_id)
        promoted = prev_status == "INCOMPLETE" and routed.is_valid
        if promoted and app.app_id not in result.promoted_app_ids:
            result.promoted_app_ids.append(app.app_id)
        if routed.is_valid and (promoted or before != _score_snapshot(persisted)):
            if self.require_object_storage:
                for document in applicant_to_ingested(persisted, self.storage_manager.minio_bucket).documents:
                    if self.storage_manager.object_exists(document.minio_key, document.minio_bucket):
                        continue
                    if not self.storage_manager.update_applicant_status(
                        app_id=app.app_id,
                        status=GateStatus.ERROR.value,
                        routing_destination=GateRoutingDestination.HUMAN_REVIEW.value,
                    ):
                        raise RuntimeError(f"Could not persist storage error for {app.app_id}")
                    raise RuntimeError(
                        f"Document object is unavailable for {app.app_id}: "
                        f"s3://{document.minio_bucket}/{document.minio_key}"
                    )
            if app.app_id not in result.affected_ids:
                result.affected_ids.append(app.app_id)

    def _match_applicant(self, row: Dict[str, Any]) -> Tuple[Optional[Applicant], str]:
        """Match incoming row to an existing Applicant by email or DOB fallback.

        Returns (matched_applicant, identifier_used_or_fallback).
        """
        email = _get_val_by_aliases(
            row,
            ["email", "email_address", "student_email", "e_mail", "student_email_address"],
        )
        dob = _get_val_by_aliases(
            row,
            ["dob", "date_of_birth", "birth_date", "birthdate"],
        )
        student_id = _get_val_by_aliases(
            row,
            ["student_id", "cb_id", "cbid", "act_id", "id", "candidate_id"],
        )

        identifier = email or dob or student_id or "UNKNOWN_STUDENT"

        applicant = self.storage_manager.find_applicant_by_email_or_dob(email=email, dob=dob)
        return applicant, identifier

    def ingest_college_board(self, file_path: Union[str, Path]) -> ScoreIngestResult:
        """Parse College Board file (SAT subscores and AP scores).

        - SAT: parses Math and EBRW subscores.
        - AP: parses AP subject and score, appending to ap_test_scores without duplicate subject/score pairs.
        - Unmatched records are saved to OrphanTestScore.
        - Matched applicants are re-evaluated through the Manifest Gate.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"College Board input file not found: {path}")
        self._check_storage()

        result = self._new_result("COLLEGE_BOARD", path)

        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result.total_records += 1
                app, identifier = self._match_applicant(row)

                if not app:
                    # Unmatched: record as orphan
                    orphan = self.storage_manager.save_orphan_score({
                        "source": "COLLEGE_BOARD",
                        "identifier": identifier,
                        "payload": row,
                    })
                    result.orphan_count += 1
                    result.orphan_identifiers.append(identifier)
                    result.orphans.append(orphan)
                    continue

                # Matched: parse SAT subscores
                sat_math = _parse_int_by_aliases(
                    row,
                    ["sat_math", "math_score", "sat_math_score", "math", "section_math"],
                )
                sat_ebrw = _parse_int_by_aliases(
                    row,
                    [
                        "sat_ebrw",
                        "ebrw_score",
                        "sat_ebrw_score",
                        "ebrw",
                        "reading_writing",
                        "erw",
                        "evidence_based_reading_and_writing",
                    ],
                )

                # Parse AP scores from row
                new_aps: List[Tuple[str, int]] = []

                # Single AP subject & score in row
                single_subj = _get_val_by_aliases(row, ["ap_subject", "subject", "ap_course", "course"])
                single_score = _parse_int_by_aliases(row, ["ap_score", "score"])
                if single_subj and single_score is not None:
                    new_aps.append((single_subj, single_score))

                # Wide columns: ap_1_subject, ap_1_score, etc.
                norm_keys = {_normalize_col(k): k for k in row.keys()}
                for idx in range(1, 13):
                    subj_key = norm_keys.get(f"ap_{idx}_subject") or norm_keys.get(f"ap{idx}_subject")
                    score_key = norm_keys.get(f"ap_{idx}_score") or norm_keys.get(f"ap{idx}_score")
                    if subj_key and score_key:
                        s_name = row.get(subj_key)
                        s_val = row.get(score_key)
                        if s_name and s_val:
                            try:
                                new_aps.append((str(s_name).strip(), int(round(float(s_val)))))
                            except (ValueError, TypeError):
                                pass

                # List/string in ap_test_scores or ap_scores
                ap_list_raw = _get_val_by_aliases(row, ["ap_test_scores", "ap_scores", "ap_courses"])
                if ap_list_raw:
                    if ap_list_raw.startswith("["):
                        try:
                            parsed_list = json.loads(ap_list_raw)
                            for item in parsed_list:
                                if isinstance(item, dict) and "subject" in item and "score" in item:
                                    new_aps.append((item["subject"], int(item["score"])))
                        except Exception:
                            pass
                    else:
                        # e.g. "AP Calculus BC: 5; AP Physics: 4"
                        for chunk in re.split(r"[;,]", ap_list_raw):
                            if ":" in chunk:
                                parts = chunk.split(":")
                                try:
                                    new_aps.append((parts[0].strip(), int(parts[1].strip())))
                                except ValueError:
                                    pass

                # Append non-duplicate AP subject/score pairs
                current_aps = list(app.ap_test_scores or [])
                updated_aps = False
                for subj, sc in new_aps:
                    if not _is_duplicate_ap(current_aps, subj, sc):
                        current_aps.append({"subject": subj, "score": sc})
                        updated_aps = True

                # Only a committed change can enter the summary handoff.
                before = _score_snapshot(app)
                prev_status = app.status
                persisted = self.storage_manager.update_applicant_scores(
                    app_id=app.app_id,
                    sat_math=sat_math if sat_math is not None else app.sat_math,
                    sat_ebrw=sat_ebrw if sat_ebrw is not None else app.sat_ebrw,
                    ap_test_scores=current_aps if updated_aps else None,
                )
                self._record_matched_update(result, app, before, persisted, prev_status)

        self._write_handoff(result)
        return result

    def ingest_act(self, file_path: Union[str, Path]) -> ScoreIngestResult:
        """Parse ACT file (composite score and section scores).

        - Parses ACT composite and section scores (English, Math, Reading, Science, Writing).
        - Unmatched records are saved to OrphanTestScore.
        - Matched applicants are re-evaluated through the Manifest Gate.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"ACT input file not found: {path}")
        self._check_storage()

        result = self._new_result("ACT", path)

        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                result.total_records += 1
                app, identifier = self._match_applicant(row)

                if not app:
                    orphan = self.storage_manager.save_orphan_score({
                        "source": "ACT",
                        "identifier": identifier,
                        "payload": row,
                    })
                    result.orphan_count += 1
                    result.orphan_identifiers.append(identifier)
                    result.orphans.append(orphan)
                    continue

                # Parse ACT composite
                act_comp = _parse_int_by_aliases(
                    row,
                    ["act_composite", "composite", "composite_score", "act_score", "superscored_act_score"],
                )

                # Parse section scores
                sections = {
                    "act_english": _parse_int_by_aliases(row, ["act_english", "english", "english_score"]),
                    "act_math": _parse_int_by_aliases(row, ["act_math", "math", "math_score"]),
                    "act_reading": _parse_int_by_aliases(row, ["act_reading", "reading", "reading_score"]),
                    "act_science": _parse_int_by_aliases(row, ["act_science", "science", "science_score"]),
                    "act_writing": _parse_int_by_aliases(row, ["act_writing", "writing", "writing_score"]),
                }

                before = _score_snapshot(app)
                prev_status = app.status
                persisted = self.storage_manager.update_applicant_scores(
                    app_id=app.app_id,
                    act_composite=act_comp if act_comp is not None else app.act_composite,
                    act_sections=sections,
                )
                self._record_matched_update(result, app, before, persisted, prev_status)

        self._write_handoff(result)
        return result

    async def ingest_college_board_async(self, file_path: Union[str, Path]) -> ScoreIngestResult:
        """Asynchronous delta ingestion for College Board test scores."""
        return await asyncio.to_thread(self.ingest_college_board, file_path)

    async def ingest_act_async(self, file_path: Union[str, Path]) -> ScoreIngestResult:
        """Asynchronous delta ingestion for ACT test scores."""
        return await asyncio.to_thread(self.ingest_act, file_path)
