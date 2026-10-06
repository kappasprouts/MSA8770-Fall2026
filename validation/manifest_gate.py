"""Deterministic Manifest Validation Gate (Component 3: Completed Check).

Component 3 as specified in Architecture Section 4:
- Evaluates ingested applications against institutional policies.yaml.
- Enforces 3-way deterministic routing based strictly on metadata fields and file presence/integrity:
  * VALID -> status: "READY_FOR_REVIEW" (application packet complete, ready for handoff).
  * INCOMPLETE -> status: "INCOMPLETE" (missing required files/metadata -> Applicant Packet Update queue).
  * ERROR -> status: "ERROR" (corrupted/missing magic bytes/size violation -> Human Review queue).
- Enforces the 2 Letters of Recommendation (LOR 1 and LOR 2) requirement.
- Generates structured summary results, reports, and affected_ids list.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

from config import (
    get_checklist,
    get_file_constraints,
    get_required_applicant_fields,
    get_routing_rules,
    load_policies,
)
from ingestion.batch_ingest import IngestedApplication, IngestedDocument


class GateStatus(str, Enum):
    """3-way deterministic gate status."""
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    VALID = "READY_FOR_REVIEW"  # Canonical alias: VALID routes to status "READY_FOR_REVIEW"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"

    def __eq__(self, other):
        if (other == "VALID" or other == "READY_FOR_REVIEW") and self.value == "READY_FOR_REVIEW":
            return True
        return super().__eq__(other)

    def __hash__(self):
        return hash(self.value)


class GateRoutingDestination(str, Enum):
    """Destination targets for deterministic gate routing."""
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPLICANT_PACKET_UPDATE = "Applicant Packet Update"
    HUMAN_REVIEW = "Human Review"


@dataclass
class RoutedApplicant:
    """Outcome of manifest gate evaluation for a single applicant."""
    applicant_id: str
    status: GateStatus
    routing_destination: str
    is_valid: bool
    missing_documents: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    documents_present: List[str] = field(default_factory=list)
    total_documents: int = 0
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class ManifestGateResult:
    """Batch-level outcome of manifest gate evaluation."""
    total_processed: int
    total_valid: int
    total_incomplete: int
    total_error: int
    routed_applicants: List[RoutedApplicant] = field(default_factory=list)
    affected_ids: List[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.affected_ids and self.routed_applicants:
            self.affected_ids = [
                app.applicant_id
                for app in self.routed_applicants
                if app.status == GateStatus.READY_FOR_REVIEW or app.status == GateStatus.VALID
            ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "total_valid": self.total_valid,
            "total_incomplete": self.total_incomplete,
            "total_error": self.total_error,
            "affected_ids": self.affected_ids,
            "evaluated_at": self.evaluated_at,
            "routed_applicants": [app.to_dict() for app in self.routed_applicants],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class ManifestValidationGate:
    """Deterministic validation gate applying 3-way routing logic based on policies.yaml."""

    # Map aliases to canonical checklist keys
    CANONICAL_ALIASES = {
        "official_transcript": "transcript",
        "transcript": "transcript",
        "academic_transcript": "transcript",
        "application_form": "application_form",
        "common_app_application": "application_form",
        "personal_statement": "personal_statement",
        "recommendation_letter_1": "recommendation_letter_1",
        "recommendation_letter_2": "recommendation_letter_2",
        "lor_1": "recommendation_letter_1",
        "lor_2": "recommendation_letter_2",
        "counselor_recommendation": "recommendation_letter_1",
        "teacher_recommendation": "recommendation_letter_2",
    }

    def __init__(self, config_path: Optional[Path] = None):
        self.policies = load_policies(config_path)
        self.file_constraints = self.policies.get("file_constraints", {})
        self.checklist = self.policies.get("checklists", {}).get("first_year", {})
        self.required_docs = self.checklist.get(
            "required_documents",
            [
                "application_form",
                "transcript",
                "personal_statement",
                "recommendation_letter_1",
                "recommendation_letter_2",
            ],
        )
        self.required_fields = self.policies.get(
            "required_applicant_fields",
            [
                "App_ID",
                "First_Name",
                "Last_Name",
                "Date_Of_Birth",
                "Email_Address",
                "Name_of_HS",
                "Intended_Major",
                "Admission_Year",
                "Admission_Term",
            ],
        )
        self.routing_rules = self.policies.get(
            "routing_rules",
            {
                "on_valid": "READY_FOR_REVIEW",
                "on_incomplete": "Applicant Packet Update",
                "on_error": "Human Review",
                "on_invalid": "Human Review",
            },
        )

    def evaluate_applicant(self, app: IngestedApplication) -> RoutedApplicant:
        """Evaluate a single ingested applicant packet and determine 3-way route strictly
        based on metadata fields and file presence/integrity:
        - VALID -> status: "READY_FOR_REVIEW" (application packet complete, ready for handoff)
        - INCOMPLETE -> status: "INCOMPLETE" (missing required files -> Applicant Packet Update)
        - ERROR -> status: "ERROR" (corrupted/missing magic bytes/size violation -> Human Review)
        """
        missing_docs: List[str] = []
        missing_fields: List[str] = []
        errors: List[str] = []

        # 1. Collect Trust Boundary 1 perimeter integrity errors (corrupted, magic bytes mismatch, size limits)
        seen_errors: Set[str] = set()
        for err in app.trust_boundary_errors:
            if err and err not in seen_errors:
                errors.append(err)
                seen_errors.add(err)

        for doc in app.documents:
            if not doc.exists:
                e = f"Document missing from disk: {doc.filename}"
                if e not in seen_errors:
                    errors.append(e)
                    seen_errors.add(e)
            elif not doc.is_readable:
                err_desc = doc.error_message or f"Document '{doc.filename}' failed integrity check."
                if err_desc not in seen_errors:
                    errors.append(err_desc)
                    seen_errors.add(err_desc)
            allowed_mimes = self.file_constraints.get("allowed_mime_types", ["application/pdf"])
            if doc.mime_type not in allowed_mimes:
                e = f"Invalid MIME type '{doc.mime_type}' for document '{doc.filename}'"
                if e not in seen_errors:
                    errors.append(e)
                    seen_errors.add(e)

        max_packet_bytes = self.file_constraints.get("max_packet_size_bytes")
        if max_packet_bytes is not None:
            packet_bytes = sum(int(doc.file_size_bytes or 0) for doc in app.documents)
            if packet_bytes > max_packet_bytes:
                errors.append(
                    f"Packet size {packet_bytes} bytes exceeds maximum {max_packet_bytes} bytes"
                )

        # 2. Check Required Applicant Metadata Fields
        for req_field in self.required_fields:
            val = app.metadata.get(req_field)
            if val is None or str(val).strip() == "" or str(val).lower() == "nan":
                missing_fields.append(req_field)

        # 3. Check Required Document Checklist Items (only from valid/existing documents)
        present_types: Set[str] = set()
        distinct_lors: Set[str] = set()

        for doc in app.documents:
            if doc.exists and doc.is_readable:
                c_type = self.CANONICAL_ALIASES.get(doc.doc_type, doc.doc_type)
                present_types.add(c_type)
                present_types.add(doc.doc_type)
                if "recommendation_letter" in doc.doc_type or "lor" in doc.doc_type:
                    checksum = (doc.sha256_checksum or "").lower()
                    if re.fullmatch(r"[0-9a-f]{64}", checksum) and checksum != "0" * 64:
                        distinct_lors.add(f"sha256:{checksum}")
                    else:
                        distinct_lors.add(f"key:{doc.minio_key or doc.filename}")

        # Recognize delta-ingested test scores in metadata as satisfying test score documents
        has_sat = bool(
            app.metadata.get("sat_math")
            or app.metadata.get("sat_ebrw")
            or app.metadata.get("Superscored_SAT_Score")
        )
        has_act = bool(
            app.metadata.get("act_composite")
            or app.metadata.get("Superscored_ACT_Score")
        )
        if has_sat or has_act:
            present_types.add("standardized_test_score")

        if getattr(app, "ap_test_scores", None) or app.metadata.get("ap_test_scores"):
            present_types.add("advanced_coursework_and_ap_scores")

        for req_doc in self.required_docs:
            c_req = self.CANONICAL_ALIASES.get(req_doc, req_doc)

            # Special check for 2 LORs
            if req_doc in ("recommendation_letter_1", "recommendation_letter_2", "recommendation_letter"):
                if req_doc == "recommendation_letter_1" and len(distinct_lors) < 1:
                    missing_docs.append("recommendation_letter_1")
                elif req_doc == "recommendation_letter_2" and len(distinct_lors) < 2:
                    missing_docs.append("recommendation_letter_2")
                elif req_doc == "recommendation_letter" and len(distinct_lors) < 1:
                    missing_docs.append("recommendation_letter")
            else:
                if c_req not in present_types and req_doc not in present_types:
                    missing_docs.append(req_doc)

        # 4. Resolve 3-Way Deterministic Routing
        # Precedence: ERROR > INCOMPLETE > VALID
        if errors:
            status = GateStatus.ERROR
            routing = self.routing_rules.get("on_error", GateRoutingDestination.HUMAN_REVIEW.value)
            is_valid = False
        elif missing_docs or missing_fields:
            status = GateStatus.INCOMPLETE
            routing = self.routing_rules.get(
                "on_incomplete", GateRoutingDestination.APPLICANT_PACKET_UPDATE.value
            )
            is_valid = False
        else:
            status = GateStatus.READY_FOR_REVIEW
            routing = self.routing_rules.get(
                "on_valid", GateRoutingDestination.READY_FOR_REVIEW.value
            )
            is_valid = True

        return RoutedApplicant(
            applicant_id=app.applicant_id,
            status=status,
            routing_destination=routing,
            is_valid=is_valid,
            missing_documents=missing_docs,
            missing_fields=missing_fields,
            errors=errors,
            documents_present=[d.filename for d in app.documents],
            total_documents=len(app.documents),
            details={
                "metadata_fields_count": len(app.metadata),
                "subfolder": str(app.subfolder_path) if app.subfolder_path else None,
            },
        )

    def evaluate_batch(self, applications: List[IngestedApplication]) -> ManifestGateResult:
        """Evaluate a list of ingested applications across the manifest validation gate."""
        routed: List[RoutedApplicant] = []
        valid_cnt = 0
        incomplete_cnt = 0
        error_cnt = 0
        affected_ids: List[str] = []

        for app in applications:
            result = self.evaluate_applicant(app)
            routed.append(result)
            if result.status == GateStatus.READY_FOR_REVIEW or result.status == GateStatus.VALID:
                valid_cnt += 1
                affected_ids.append(app.applicant_id)
            elif result.status == GateStatus.INCOMPLETE:
                incomplete_cnt += 1
            elif result.status == GateStatus.ERROR:
                error_cnt += 1

        return ManifestGateResult(
            total_processed=len(applications),
            total_valid=valid_cnt,
            total_incomplete=incomplete_cnt,
            total_error=error_cnt,
            routed_applicants=routed,
            affected_ids=affected_ids,
        )
