# Admissions Officer Review Console UI/UX Specifications

**Component**: Web Application (UI)  
**Technology Stack**: Next.js 14 (App Router) + Tailwind CSS + FastAPI Backend  
**Architecture Reference**: [docs_architecture_section_4.md](../../docs_architecture_section_4.md) (Component 8)

---

## 1. Overview & Human Authority Governance

The Review Console is the central human-in-the-loop web interface through which authorized admissions officers review pre-compiled dossiers and record final admissions decisions.

### Institutional Policy Mandates
1. **Admissions Authority (`POL-HUMAN-01`)**: All AI summaries are labeled **Advisory Only**. Only human admissions officers possess authority to record final decisions (`Accept`, `Decline`, `Waitlist`).
2. **Personal Statement Reading (`POL-ESSAY-01`)**: Because personal statements are stripped from automated AI pipelines to prevent algorithmic bias, the console presents the essay in a dedicated reading pane with prominent disclosure of human-only evaluation.
3. **High School Context Display (`POL-AP-01`)**: Student AP coursework is explicitly visualized alongside the issuing high school's available AP course offerings and four-year AP cap.

---

## 2. Role-Based Access Control (RBAC)

| Role | Permissions |
| :--- | :--- |
| `AdmissionsOfficer` | View dossiers in `READY_FOR_REVIEW` queue; read personal essays; record decisions (`Accept`, `Decline`, `Waitlist`). |
| `SeniorCounselor` | Access `COUNSELOR_REVIEW` queue; resolve document mismatches, waivers, and nonstandard exceptions (`POL-EXC-01`). |
| `SystemAuditor` | Read-only access to dossiers, immutable `audit_logs`, and model bypass records. |

---

## 3. UI Layout & Wireframe Specifications

```text
+-----------------------------------------------------------------------------------------------+
| Riverview State University | Admissions Review Console            [Officer: Avery Adams (v)]   |
+-----------------------------------------------------------------------------------------------+
| Queue: [READY_FOR_REVIEW (14)]  | [AWAITING_MATERIALS (3)] | [INCOMPLETE (2)]                  |
+-----------------------------------------------------------------------------------------------+
| APPLICANT DOSSIER: Alex Bennett (APP-001)                    Application Type: First-Year     |
| High School: Northfield Regional HS (HS-001)                 Intended Major: Studio Art       |
+-----------------------------------------------------------------------------------------------+
| [CARD 1: High School Rigor Context]     | [CARD 2: AI Rigor Summary (Advisory - POL-HUMAN-01)]|
| - School Max AP Cap: 5 Courses           | - Completed 5 AP Courses (100% of available cap)    |
| - Offered: AP US Hist, AP Chem, AP Calc  | - Cumulative GPA: 3.86 (Unweighted) / 4.68 (W)      |
| - Student Completed: 5 Courses           | - Test-Optional: SAT 1500 submitted (POL-TEST-01)   |
| Status: FULL RIGOR PARITY                | Citations: [POL-AP-01], [POL-FT-01], [POL-TEST-01]  |
+-----------------------------------------------------------------------------------------------+
| [DEDICATED HUMAN ESSAY PANE - POL-ESSAY-01 COMPLIANCE]                                       |
| Banner: [!] ALGORITHMIC BIAS SAFEGUARD ENFORCED                                               |
| Notice: Personal statement was excluded from AI model inference and embedding indexes.         |
|         Holistic evaluation of voice, lived experience, and character is conducted solely      |
|         by the human admissions officer.                                                      |
|                                                                                               |
| "Personal Statement: My Journey Through Generative Art..."                                    |
| [Scrollable reader displaying formatted text from personal_statement.pdf]                     |
+-----------------------------------------------------------------------------------------------+
| [ARCHIVAL DOCUMENTS VIEWER (MinIO Presigned URLs)]                                            |
| [View Transcript.pdf]  [View Recommendation_1.pdf]  [View Activities_and_Awards.pdf]          |
+-----------------------------------------------------------------------------------------------+
| FINAL ADMISSIONS DECISION ACTION BAR (POL-HUMAN-01)                                           |
| Mandatory Rationale: [                                                            ]           |
|                                                                                               |
| [  ACCEPT CANDIDATE  ]      [  WAITLIST CANDIDATE  ]      [  DECLINE CANDIDATE  ]             |
+-----------------------------------------------------------------------------------------------+
```

---

## 4. Decision Recording Contract

When an officer records a decision, the console issues a `POST` request to the backend:

* **Endpoint**: `POST /applications/{applicant_id}/decision`
* **Request Payload**:
  ```json
  {
    "officer_id": "OFFICER-4821",
    "decision": "ACCEPT",
    "decision_rationale": "Outstanding academic rigor matching school AP cap, verified coursework, and compelling personal narrative.",
    "reviewed_documents": [
      "transcript.pdf",
      "personal_statement.pdf",
      "recommendation_letter_1.pdf"
    ]
  }
  ```
* **State Updates**:
  1. Updates `applications.status = 'DECIDED'`.
  2. Records the archive action in the review console's workflow state.
  3. Appends an immutable record to `audit_logs` tracking officer ID, timestamp, and decision rationale.
