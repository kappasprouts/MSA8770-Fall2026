"""Deterministic manifest validation gate for inbound applicant packets.

Enforces Trust Boundary 1 (perimeter constraints), required document checklists,
file size/MIME verification, and status/routing assignment based on YAML policy rules.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from policy import derive_routing_destination, get_checklist, get_file_constraints, get_routing_rules, get_status_priority, load_policies
from ingestion.validation.models import (
    DocumentManifestItem,
    PacketManifest,
    ValidationFinding,
    ValidationResult,
    ValidationStatus,
)


class ManifestValidator:
    """Validates packet manifests against institutional YAML policies."""

    def __init__(self, config_path: Optional[Path] = None):
        self.policies = load_policies(config_path)
        self.file_constraints = self.policies.get("file_constraints", {})
        self.checklists = self.policies.get("checklists", {})
        self.status_priority = self.policies.get(
            "status_priority",
            ["STOPPED", "COUNSELOR_REVIEW", "REPLACEMENT_REQUESTED", "INCOMPLETE", "AWAITING_MATERIALS", "READY_FOR_REVIEW"],
        )
        self.routing_rules = self.policies.get(
            "routing_rules",
            {
                "on_invalid": "Human Review",
                "on_incomplete": "Applicant Packet Update",
                "on_ready": "READY_FOR_REVIEW",
            },
        )

    def validate(self, manifest: PacketManifest) -> ValidationResult:
        """Execute deterministic validation on an inbound applicant packet manifest."""
        findings: List[ValidationFinding] = []

        # 1. Perimeter Checks: File Constraints (Trust Boundary 1)
        self._check_file_constraints(manifest, findings)

        # 2. Document-to-Applicant ID Matching (POL-ID-01)
        self._check_applicant_id_consistency(manifest, findings)

        # 3. Required Document Checklist Completeness (POL-FT-01, POL-TR-01, etc.)
        self._check_checklist_completeness(manifest, findings)

        # 4. Document Readability Checks (POL-READ-01)
        self._check_document_readability(manifest, findings)

        # 5. Resolve Final Status using Priority Matrix
        final_status = self._resolve_status(findings)
        is_valid = final_status == ValidationStatus.READY_FOR_REVIEW

        # 6. Route Application Based on Architectural Gate Rules
        routing_destination = self._determine_routing(final_status)

        return ValidationResult(
            applicant_id=manifest.applicant_id,
            is_valid=is_valid,
            status=final_status,
            routing_destination=routing_destination,
            findings=findings,
        )

    def _check_file_constraints(self, manifest: PacketManifest, findings: List[ValidationFinding]) -> None:
        allowed_mimes = set(self.file_constraints.get("allowed_mime_types", ["application/pdf"]))
        allowed_exts = set(self.file_constraints.get("allowed_extensions", [".pdf"]))
        max_file_size = self.file_constraints.get("max_file_size_bytes", 15 * 1024 * 1024)
        min_file_size = self.file_constraints.get("min_file_size_bytes", 1024)
        max_packet_size = self.file_constraints.get("max_packet_size_bytes", 50 * 1024 * 1024)

        total_packet_size = sum(doc.file_size_bytes for doc in manifest.documents)
        if total_packet_size > max_packet_size:
            findings.append(
                ValidationFinding(
                    policy_id="PERIM-SIZE-01",
                    rule="Total packet size must not exceed configured threshold",
                    severity="ERROR",
                    status=ValidationStatus.STOPPED,
                    message=f"Total packet size {total_packet_size} bytes exceeds limit of {max_packet_size} bytes.",
                    details={"total_bytes": total_packet_size, "limit": max_packet_size},
                )
            )

        for doc in manifest.documents:
            # MIME type verification
            if doc.mime_type not in allowed_mimes:
                findings.append(
                    ValidationFinding(
                        policy_id="PERIM-MIME-01",
                        rule="File MIME type must match allowed list",
                        severity="ERROR",
                        status=ValidationStatus.STOPPED,
                        message=f"Disallowed MIME type '{doc.mime_type}' for document '{doc.filename}'.",
                        document_type=doc.doc_type,
                        details={"filename": doc.filename, "mime_type": doc.mime_type},
                    )
                )

            # Extension verification
            ext = Path(doc.filename).suffix.lower()
            if ext not in allowed_exts:
                findings.append(
                    ValidationFinding(
                        policy_id="PERIM-EXT-01",
                        rule="File extension must match allowed list",
                        severity="ERROR",
                        status=ValidationStatus.STOPPED,
                        message=f"File extension '{ext}' for '{doc.filename}' is not permitted.",
                        document_type=doc.doc_type,
                        details={"filename": doc.filename, "extension": ext},
                    )
                )

            # Individual file size verification
            if doc.file_size_bytes > max_file_size:
                findings.append(
                    ValidationFinding(
                        policy_id="PERIM-FILESIZE-01",
                        rule="File size must not exceed individual limit",
                        severity="ERROR",
                        status=ValidationStatus.STOPPED,
                        message=f"File '{doc.filename}' ({doc.file_size_bytes} bytes) exceeds {max_file_size} bytes limit.",
                        document_type=doc.doc_type,
                        details={"filename": doc.filename, "size": doc.file_size_bytes, "limit": max_file_size},
                    )
                )
            elif doc.file_size_bytes < min_file_size:
                findings.append(
                    ValidationFinding(
                        policy_id="PERIM-FILESIZE-02",
                        rule="File must satisfy minimum size requirement to prevent empty/corrupted uploads",
                        severity="ERROR",
                        status=ValidationStatus.COUNSELOR_REVIEW,
                        message=f"File '{doc.filename}' is smaller than minimum required {min_file_size} bytes.",
                        document_type=doc.doc_type,
                        details={"filename": doc.filename, "size": doc.file_size_bytes, "min_limit": min_file_size},
                    )
                )

    def _check_applicant_id_consistency(self, manifest: PacketManifest, findings: List[ValidationFinding]) -> None:
        for doc in manifest.documents:
            if doc.applicant_id and doc.applicant_id != manifest.applicant_id:
                findings.append(
                    ValidationFinding(
                        policy_id="POL-ID-01",
                        rule="Document applicant ID must match packet applicant ID",
                        severity="ERROR",
                        status=ValidationStatus.COUNSELOR_REVIEW,
                        message=(
                            f"Document '{doc.filename}' belongs to applicant '{doc.applicant_id}', "
                            f"mismatched with packet applicant '{manifest.applicant_id}'."
                        ),
                        document_type=doc.doc_type,
                        details={"packet_id": manifest.applicant_id, "doc_applicant_id": doc.applicant_id},
                    )
                )

    def _check_checklist_completeness(self, manifest: PacketManifest, findings: List[ValidationFinding]) -> None:
        checklist_cfg = self.checklists.get(
            manifest.application_type, self.checklists.get("first_year", {})
        )
        required_docs = checklist_cfg.get("required_documents", [])
        policy_ref = checklist_cfg.get("policy_reference", "POL-FT-01")

        present_doc_types = {doc.doc_type for doc in manifest.documents}

        for req in required_docs:
            if req not in present_doc_types:
                findings.append(
                    ValidationFinding(
                        policy_id=policy_ref,
                        rule="Required checklist documents must be present in submission packet",
                        severity="WARNING",
                        status=ValidationStatus.AWAITING_MATERIALS,
                        message=f"Required document '{req}' is missing from the packet.",
                        document_type=req,
                        details={"missing_document": req, "application_type": manifest.application_type},
                    )
                )

    def _check_document_readability(self, manifest: PacketManifest, findings: List[ValidationFinding]) -> None:
        checklist_cfg = self.checklists.get(
            manifest.application_type, self.checklists.get("first_year", {})
        )
        required_docs = set(checklist_cfg.get("required_documents", []))

        for doc in manifest.documents:
            if not doc.is_readable:
                is_req = doc.doc_type in required_docs
                status = ValidationStatus.REPLACEMENT_REQUESTED if is_req else ValidationStatus.COUNSELOR_REVIEW
                findings.append(
                    ValidationFinding(
                        policy_id="POL-READ-01",
                        rule="Submitted documents must meet legibility thresholds",
                        severity="ERROR" if is_req else "WARNING",
                        status=status,
                        message=f"Document '{doc.filename}' failed legibility check.",
                        document_type=doc.doc_type,
                        details={"filename": doc.filename, "is_required": is_req},
                    )
                )

    def _resolve_status(self, findings: List[ValidationFinding]) -> ValidationStatus:
        if not findings:
            return ValidationStatus.READY_FOR_REVIEW

        finding_statuses = {f.status.value for f in findings}
        for prio in self.status_priority:
            if prio in finding_statuses:
                return ValidationStatus(prio)

        return ValidationStatus.READY_FOR_REVIEW

    def _determine_routing(self, status: ValidationStatus) -> str:
        """Derive the queue from status using the current policy rules."""
        return derive_routing_destination(status.value, self.routing_rules)
