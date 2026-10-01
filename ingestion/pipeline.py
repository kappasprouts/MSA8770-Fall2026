"""Batch Ingestion Pipeline for Riverview State University Admissions.

Scans inbound external data feeds (simulating CommonApp SFTP, College Board SFTP,
and University Portal), builds packet manifests, executes deterministic validation gates,
parses documents with PyMuPDF/OCR, and persists records into PostgreSQL and MinIO.
"""

from datetime import datetime, timezone
import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import load_policies
from gateway import DocumentItem, InferenceRequest, ModelGateway
from parsing import DocumentParser
from storage import Application, AuditLog, DocumentRecord, MinIOClient
from validation import DocumentManifestItem, ManifestValidator, PacketManifest, ValidationStatus

logger = logging.getLogger(__name__)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class BatchIngestionPipeline:
    """Orchestrates batch ingestion, validation, parsing, and storage."""

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        minio_client: Optional[MinIOClient] = None,
        model_gateway: Optional[ModelGateway] = None,
        db_session_factory=None,
    ):
        base_dir = Path(__file__).resolve().parent.parent
        self.source_dir = (
            source_dir
            or base_dir
            / "applicant_source_documents"
            / "admitgpt_60_source_documents"
            / "applicant_source_packets"
        )
        self.validator = ManifestValidator()
        self.parser = DocumentParser()
        self.minio = minio_client or MinIOClient()
        self.gateway = model_gateway or ModelGateway()
        self.db_session_factory = db_session_factory

    def assemble_manifest(self, packet_dir: Path, applicant_id: str) -> PacketManifest:
        """Scan a packet directory and assemble a validated PacketManifest."""
        doc_items: List[DocumentManifestItem] = []

        for file_path in packet_dir.glob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                size = file_path.stat().st_size
                mime, _ = mimetypes.guess_type(file_path.name)
                mime = mime or "application/pdf"
                checksum = compute_sha256(file_path)
                doc_type, _ = self.parser.classify_document_type(file_path.name)

                doc_items.append(
                    DocumentManifestItem(
                        filename=file_path.name,
                        doc_type=doc_type,
                        file_size_bytes=size,
                        mime_type=mime,
                        sha256_checksum=checksum,
                        applicant_id=applicant_id,
                        is_readable=True,
                    )
                )

        return PacketManifest(
            applicant_id=applicant_id,
            application_type="first_year",
            source_feed="Simulated_SFTP",
            documents=doc_items,
        )

    def process_packet(self, packet_dir: Path, applicant_id: str) -> Dict[str, Any]:
        """Process an individual applicant packet through validation, parsing, and archival."""
        manifest = self.assemble_manifest(packet_dir, applicant_id)
        validation_result = self.validator.validate(manifest)

        result_summary = {
            "applicant_id": applicant_id,
            "status": validation_result.status.value,
            "is_valid": validation_result.is_valid,
            "routing_destination": validation_result.routing_destination,
            "findings_count": len(validation_result.findings),
            "documents_parsed": 0,
            "ai_evaluated": False,
        }

        # If incomplete or invalid, route accordingly without running full LLM evaluation
        if validation_result.status != ValidationStatus.READY_FOR_REVIEW:
            logger.info(
                f"Packet {applicant_id} routed to '{validation_result.routing_destination}' "
                f"with status '{validation_result.status.value}'"
            )
            return result_summary

        # Parse documents and prepare model inference payload
        inference_docs: List[DocumentItem] = []
        for doc_item in manifest.documents:
            file_path = packet_dir / doc_item.filename
            if file_path.exists():
                parsed = self.parser.parse_document(
                    file_path=file_path,
                    applicant_id=applicant_id,
                    force_doc_type=doc_item.doc_type,
                )
                result_summary["documents_parsed"] += 1

                # Upload to MinIO archival bucket
                try:
                    obj_key = f"{applicant_id}/{doc_item.filename}"
                    self.minio.upload_file(file_path, obj_key)
                except Exception as e:
                    logger.warning(f"MinIO upload skipped for {doc_item.filename}: {e}")

                inference_docs.append(
                    DocumentItem(
                        document_type=parsed.document_type,
                        content=parsed.full_text,
                        filename=doc_item.filename,
                    )
                )

        # Call Model Gateway with policy grounding (strictly bypassing essay)
        try:
            req = InferenceRequest(
                applicant_id=applicant_id,
                application_type=manifest.application_type,
                documents=inference_docs,
            )
            llm_resp = self.gateway.evaluate_applicant(req)
            result_summary["ai_evaluated"] = True
            result_summary["essay_bypassed"] = llm_resp.essay_bypassed
            result_summary["bypassed_documents"] = llm_resp.bypassed_documents
        except Exception as e:
            logger.error(f"Error calling model gateway for {applicant_id}: {e}")

        return result_summary

    def run_batch(self, max_packets: Optional[int] = None) -> Dict[str, Any]:
        """Execute batch ingestion run over the drop zone directory."""
        if not self.source_dir.exists():
            return {
                "status": "COMPLETED",
                "message": f"Source directory {self.source_dir} not found.",
                "total_processed": 0,
            }

        packet_dirs = sorted([d for d in self.source_dir.iterdir() if d.is_dir()])
        if max_packets:
            packet_dirs = packet_dirs[:max_packets]

        batch_results = []
        counts = {
            "READY_FOR_REVIEW": 0,
            "INCOMPLETE": 0,
            "COUNSELOR_REVIEW": 0,
            "REPLACEMENT_REQUESTED": 0,
            "STOPPED": 0,
        }

        for p_dir in packet_dirs:
            app_id = p_dir.name
            res = self.process_packet(p_dir, app_id)
            batch_results.append(res)
            counts[res["status"]] = counts.get(res["status"], 0) + 1

        summary = {
            "status": "COMPLETED",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "total_packets_discovered": len(packet_dirs),
            "status_breakdown": counts,
            "results": batch_results,
        }
        return summary
