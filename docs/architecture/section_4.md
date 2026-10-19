# Section 4: Architecture Plan

## Overview
The system architecture implements an asynchronous batch evaluation pipeline backed by relational and vector storage, isolated document parsing and LLM inference, and a human-in-the-loop review console.

## Components and Tools
1. External Data Access (Simulated for Prototype): CommonApp SFTP (applications, essays, supplements), College Board SFTP (SAT/ACT scores), and University Portal (transcripts, school profile, LORs).
2. Ingestion Layer: Python batch ingestion with FastAPI backend, triggered autonomously on an overnight schedule via APScheduler.
3. Deterministic Manifest Validation Gate: Python validation checking required checklist items using YAML rules, verifying file types/sizes, extracting metadata, and verifying application completeness. Invalid applications route to Human Review; incomplete packets route to Applicant Packet Update.
4. OCR & Document Parsing: PyMuPDF and Tesseract extracting text from PDFs/images, classifying document types, and structuring content into JSON payloads.
5. Model Gateway / LLM API: Local containerized LLM (Qwen 2.5 or gpt-oss-20b hosted via Ollama and Docker Desktop) with Python RAG and agent logic. Personal essays are skipped by design to mitigate algorithmic bias.
6. Relational Store + Review Queue: PostgreSQL (JSONB fields for applications, AI reviews, and review queue status = 'READY_FOR_REVIEW') and MinIO for raw document archival.
7. Policy Vector Store: pgvector stores policy text, embeddings, and semantic search data; the ingestion checklist rules are in `policy/ingestion_rules.yaml`.
8. Web Application (UI): Next.js / FastAPI interface with authentication/RBAC (simulated for prototype), allowing admissions officers to view pre-compiled dossiers, read personal essays, and record final decisions (Accept/Decline/Waitlist).

## Trust Boundaries
- Trust Boundary 1 (Untrusted Inbound Perimeter): Separates external data feeds from internal ingestion, enforcing MIME validation, file size limits, and manifest completeness checks.
- Trust Boundary 2 (Internal Secure Environment): Encloses PostgreSQL, MinIO, and internal services, isolating student PII and transcripts behind role-based access controls and immutable audit logs.
