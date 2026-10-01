# System Architecture & Technical Specifications

**Document Version**: 1.0  
**Status**: APPROVED  
**Related Reference**: [docs_architecture_section_4.md](../../docs_architecture_section_4.md)

---

## 1. Architectural Philosophy & Objectives

The Riverview State University admissions processing system implements an **asynchronous batch evaluation pipeline** designed around four foundational architectural principles:

1. **Deterministic Perimeter Gates**: All inbound submissions are scrutinized at an untrusted perimeter for MIME validity, file size bounds, and mandatory document completeness before any compute-intensive parsing or AI inference is permitted.
2. **Context-Grounded Rigor Evaluation**: High school academic rigor is evaluated strictly relative to the student's high school profile offerings and four-year AP cap (`POL-AP-01`), avoiding systemic bias against under-resourced schools.
3. **Mandatory Essay Algorithmic Safeguard (`POL-ESSAY-01`)**: Personal statements and essays are stripped by design from automated LLM inference prompts and vector embeddings to prevent algorithmic bias; they are routed directly to authorized human officers.
4. **Human Final Admissions Authority (`POL-HUMAN-01`)**: AI evaluation findings and workflow statuses (`READY_FOR_REVIEW`, `INCOMPLETE`, `COUNSELOR_REVIEW`) are purely advisory. Authorized admissions officers retain exclusive authority to record final decisions (`Accept`, `Decline`, `Waitlist`).

---

## 2. End-to-End Component Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant Feed as External SFTP & Portal
    participant Sched as APScheduler Service
    participant Pipe as Batch Ingestion Pipeline
    participant Gate as Deterministic Validation Gate
    participant Parser as PyMuPDF & Tesseract OCR
    participant MinIO as MinIO Object Storage
    participant DB as PostgreSQL (Relational & Audit)
    participant Model as Local LLM Gateway (Ollama)
    participant UI as Admissions Officer Console

    Note over Sched: Triggered Overnight at 02:00 UTC
    Sched->>Pipe: Execute overnight batch run
    Pipe->>Feed: Scan drop zone for applicant packets
    Feed-->>Pipe: Packet files (transcripts, essays, forms)

    Pipe->>Gate: Validate packet manifest
    Note over Gate: Trust Boundary 1 Perimeter Enforcement
    Gate->>Gate: Verify MIME, size <= 15MB, checksums
    Gate->>Gate: Evaluate checklist completeness against policies.yaml

    alt Incomplete Submission
        Gate-->>Pipe: Status: INCOMPLETE (Missing required items)
        Pipe->>DB: Persist Application (routing: "Applicant Packet Update")
        Pipe->>DB: Write Immutable Audit Log
    else Invalid / Malformed / Corrupt
        Gate-->>Pipe: Status: STOPPED / COUNSELOR_REVIEW / REPLACEMENT_REQUESTED
        Pipe->>DB: Persist Application (routing: "Human Review")
        Pipe->>DB: Write Immutable Audit Log
    else Valid & Complete
        Gate-->>Pipe: Status: READY_FOR_REVIEW
        Pipe->>Parser: Parse documents (PDF native + OCR fallback)
        Parser->>Parser: Extract text, classify doc types, structure JSON
        Parser-->>MinIO: Archive raw documents into s3://applicant-documents/
        Parser-->>DB: Record document metadata & checksums

        Note over Pipe,Model: Safeguard: Filter out personal_statement (POL-ESSAY-01)
        Pipe->>Model: Invoke evaluation (excluding essay content)
        Model->>Model: Inject policy grounding & context
        Model-->>Pipe: Structured advisory review & policy citations

        Pipe->>DB: Update Application (status='READY_FOR_REVIEW', JSONB AI review)
        Pipe->>DB: Record pipeline completion in AuditLog

        Note over UI: Human-in-the-Loop Review
        UI->>DB: Fetch dossier with status='READY_FOR_REVIEW'
        UI->>MinIO: Retrieve raw documents & personal statement
        UI->>UI: Admissions officer reads essay & evaluates dossier
        UI->>DB: Record final admissions decision (Accept/Decline/Waitlist)
    end
```

---

## 3. Trust Boundary Technical Specifications

### Trust Boundary 1: Untrusted Inbound Perimeter
* **Boundary Purpose**: Separates untrusted external feeds (CommonApp SFTP, College Board SFTP, third-party transcript portal exports) from internal compute infrastructure.
* **Perimeter Controls**:
  * **MIME Sniffing**: Inspects magic bytes and headers; permits only `application/pdf`, `image/png`, `image/jpeg`, and `image/tiff`.
  * **File Size Quotas**: Rejects files larger than 15 MB (`max_file_size_bytes: 15728640`) and packets larger than 50 MB (`max_packet_size_bytes: 52428800`). Rejects zero-byte or corrupt files under 1 KB (`min_file_size_bytes: 1024`).
  * **Path Sanitization**: Rejects paths containing directory traversal patterns (`..`, `/`, `\`).
  * **Checklist Completeness**: Matches submitted document types against institutional checklists in `config/policies.yaml`.
  * **Deterministic Routing Matrix**:
    * If missing required items: Status `INCOMPLETE` $\rightarrow$ Target: **Applicant Packet Update**.
    * If unreadable required items: Status `REPLACEMENT_REQUESTED` $\rightarrow$ Target: **Human Review**.
    * If applicant ID mismatch or ambiguous coursework: Status `COUNSELOR_REVIEW` $\rightarrow$ Target: **Human Review**.
    * If perimeter violation (disallowed MIME/size limit): Status `STOPPED` $\rightarrow$ Target: **Human Review**.

### Trust Boundary 2: Internal Secure Environment
* **Boundary Purpose**: Encloses core data stores, student PII, and internal evaluation services.
* **Security Controls**:
  * **Network Isolation**: PostgreSQL, MinIO, and local Ollama containers run on an isolated Docker network (`backend-net`) without public ingress.
  * **Immutable Audit Trail**: Every ingestion event, OCR run, LLM invocation, and decision change is appended to the `AuditLog` table with UTC timestamp and actor identifier.
  * **Algorithmic Bias Isolation**: The Model Gateway guarantees that student essays never enter LLM prompt buffers or vector embedding indexes.
  * **Presigned Access**: Document binaries stored in MinIO are never directly exposed; frontend clients receive time-limited presigned URLs (TTL: 3600 seconds).

---

## 4. Status Priority & State Transitions

When multiple findings occur within a single packet, the system evaluates status resolution in strict priority order:

$$\text{STOPPED} \succ \text{COUNSELOR\_REVIEW} \succ \text{REPLACEMENT\_REQUESTED} \succ \text{INCOMPLETE} \succ \text{READY\_FOR\_REVIEW}$$

```mermaid
stateDiagram-v2
    [*] --> Inbound_Packet
    Inbound_Packet --> Deterministic_Gate: Scan & Manifest Assembly

    Deterministic_Gate --> STOPPED: Perimeter / Security Violation
    Deterministic_Gate --> COUNSELOR_REVIEW: Ambiguity / ID Mismatch / Waiver
    Deterministic_Gate --> REPLACEMENT_REQUESTED: Corrupt / Unreadable Attachment
    Deterministic_Gate --> INCOMPLETE: Missing Required Document
    Deterministic_Gate --> READY_FOR_REVIEW: All Criteria Satisfied

    INCOMPLETE --> Applicant_Packet_Update: Route for missing documents
    STOPPED --> Human_Review_Queue: Route for manual inspection
    COUNSELOR_REVIEW --> Human_Review_Queue: Route for counselor adjudication
    REPLACEMENT_REQUESTED --> Human_Review_Queue: Route for re-request

    READY_FOR_REVIEW --> OCR_and_Storage: Parse PDF/Images & Archive
    OCR_and_Storage --> Model_Gateway: Grounded AI Rigor Evaluation (Bypass Essay)
    Model_Gateway --> Admissions_Officer_Console: Queue for Officer Adjudication

    Admissions_Officer_Console --> Final_Decision: Accept / Decline / Waitlist
    Final_Decision --> [*]
```
