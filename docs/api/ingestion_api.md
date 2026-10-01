# Ingestion Webhook & Scheduling API Specification

**Service Name**: Admissions Batch Ingestion API  
**Base URL**: `http://localhost:8000`  
**Protocol**: HTTP/1.1 / JSON  
**Implementation**: [`ingestion/app.py`](../../ingestion/app.py)

---

## 1. Endpoints Overview

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :---: |
| `GET` | `/` | Root service metadata and architecture boundaries. | No |
| `GET` | `/health` | Service health and background scheduler status. | No |
| `POST` | `/ingestion/batch/trigger` | Trigger on-demand batch ingestion run. | Yes (Internal) |
| `GET` | `/ingestion/batch/status` | Retrieve outcomes and status counts from the latest batch run. | Yes (Internal) |
| `POST` | `/ingestion/packet/{applicant_id}` | Trigger ingestion, validation, and parsing for a single packet. | Yes (Internal) |

---

## 2. Detailed Endpoint Contracts

### 2.1 `GET /`
Returns service status, architecture compliance info, and trust boundary enforcement state.

* **Response Status**: `200 OK`
* **Response Body**:
  ```json
  {
    "service": "Riverview Admissions Ingestion Service",
    "architecture_reference": "Section 4: Architecture Plan",
    "trust_boundary_1": "Enforced (MIME, size limits, and manifest completeness)",
    "status": "OPERATIONAL"
  }
  ```

---

### 2.2 `GET /health`
Liveness and readiness probe for container orchestration (Docker / Kubernetes).

* **Response Status**: `200 OK`
* **Response Body**:
  ```json
  {
    "status": "healthy",
    "service": "ingestion",
    "scheduler_available": true
  }
  ```

---

### 2.3 `POST /ingestion/batch/trigger`
Triggers an autonomous batch pass across external drop-zone folders (e.g. SFTP drop).

* **Query Parameters**:
  * `max_packets` (integer, optional): Maximum number of packets to process in this run (useful for testing).
* **Response Status**: `200 OK`
* **Response Body**:
  ```json
  {
    "status": "COMPLETED",
    "executed_at": "2026-10-01T02:00:15.123456Z",
    "total_packets_discovered": 10,
    "status_breakdown": {
      "READY_FOR_REVIEW": 9,
      "INCOMPLETE": 1,
      "COUNSELOR_REVIEW": 0,
      "REPLACEMENT_REQUESTED": 0,
      "STOPPED": 0
    },
    "results": [
      {
        "applicant_id": "APP-001",
        "status": "READY_FOR_REVIEW",
        "is_valid": true,
        "routing_destination": "READY_FOR_REVIEW",
        "findings_count": 0,
        "documents_parsed": 9,
        "ai_evaluated": true,
        "essay_bypassed": true,
        "bypassed_documents": ["personal_statement.pdf"]
      },
      {
        "applicant_id": "APP-010",
        "status": "INCOMPLETE",
        "is_valid": false,
        "routing_destination": "Applicant Packet Update",
        "findings_count": 1,
        "documents_parsed": 0,
        "ai_evaluated": false
      }
    ]
  }
  ```

---

### 2.4 `GET /ingestion/batch/status`
Returns the cached execution report of the most recent batch run.

* **Response Status**: `200 OK`
* **Response Body**: Returns the identical JSON schema as `POST /ingestion/batch/trigger`. If no batch has been executed since startup, returns:
  ```json
  {
    "status": "NO_PREVIOUS_RUN",
    "message": "No batch run has been executed yet."
  }
  ```

---

### 2.5 `POST /ingestion/packet/{applicant_id}`
Manually trigger ingestion, validation, OCR parsing, MinIO upload, and Model Gateway evaluation for a single applicant packet.

* **Path Parameters**:
  * `applicant_id` (string, required): The unique applicant identifier (e.g. `APP-001`).
* **Response Status**: `200 OK`
* **Response Body**:
  ```json
  {
    "applicant_id": "APP-001",
    "status": "READY_FOR_REVIEW",
    "is_valid": true,
    "routing_destination": "READY_FOR_REVIEW",
    "findings_count": 0,
    "documents_parsed": 9,
    "ai_evaluated": true,
    "essay_bypassed": true,
    "bypassed_documents": ["personal_statement.pdf"]
  }
  ```
* **Error Response (`404 Not Found`)**:
  ```json
  {
    "detail": "Applicant packet directory 'APP-999' not found in source feed."
  }
  ```

---

## 3. Overnight Batch Scheduling

Batch ingestion is scheduled via APScheduler in [`ingestion/scheduler.py`](../../ingestion/scheduler.py):
* **Default Schedule**: Daily at `02:00 UTC` (configurable via `BATCH_CRON_HOUR` and `BATCH_CRON_MINUTE` environment variables).
* **Execution Target**: Invokes `BatchIngestionPipeline.run_batch()`.
* **Idempotency**: Packets are hashed via SHA256; re-running ingestion does not generate duplicate document records.
