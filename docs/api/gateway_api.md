# Model Gateway & Policy Grounding Specification

**Component**: Model Gateway / LLM API  
**Engine**: Local Ollama container (`qwen2.5:14b-instruct` or `gpt-oss-20b`)  
**Implementation**: [`gateway/client.py`](../../gateway/client.py), [`gateway/grounding.py`](../../gateway/grounding.py)

---

## 1. Gateway Purpose & Governance

The Model Gateway provides structured, policy-grounded evaluation summaries for completed applicant packets. To comply with Section 4 Architecture and institutional governance policies:
1. **Advisory Authority Only (`POL-HUMAN-01`)**: The model evaluates factual academic rigor, AP offerings parity, and transcript consistency. It is strictly prohibited from emitting admissions decisions (`Accept`, `Decline`, `Waitlist`).
2. **Mandatory Personal Statement Bypass (`POL-ESSAY-01`)**:
   > To mitigate algorithmic bias in qualitative and personal narratives, personal statements/essays are **systematically stripped** from model input payloads. The gateway flags these documents as bypassed and documents the bypass reason for human review.
3. **Evidence Citations (`POL-EVID-01`)**: Every finding must cite its source document and corresponding policy rule. Missing or ambiguous data must be explicitly labeled `unknown`.

---

## 2. Gateway API Contracts

### 2.1 Request Schema: `InferenceRequest`

```json
{
  "applicant_id": "APP-001",
  "application_type": "first_year",
  "documents": [
    {
      "document_type": "official_transcript",
      "filename": "transcript.pdf",
      "content": "RIVERVIEW STATE UNIVERSITY - Academic Transcript\nStudent: Alex Bennett\nCumulative Unweighted GPA: 3.86\nWeighted GPA: 4.68\nCoursework: AP Calculus AB (Grade: A), AP Biology (Grade: A), AP US History (Grade: A)"
    },
    {
      "document_type": "personal_statement",
      "filename": "personal_statement.pdf",
      "content": "[ESSAY CONTENT SUBMITTED BY APPLICANT]"
    },
    {
      "document_type": "recommendation_letter",
      "filename": "recommendation_letter_1.pdf",
      "content": "Alex Bennett has consistently demonstrated intellectual curiosity..."
    }
  ],
  "high_school_context": {
    "school_id": "HS-001",
    "name": "Northfield Regional High School",
    "type": "public",
    "ap_courses_offered": [
      "AP United States History",
      "AP Chemistry",
      "AP English Language and Composition",
      "AP Computer Science Principles",
      "AP Calculus AB",
      "AP Biology"
    ],
    "max_ap_courses": 5
  }
}
```

---

### 2.2 Response Schema: `InferenceResponse`

When evaluated, notice how `personal_statement.pdf` is excluded from LLM inference, and `essay_bypassed` is set to `true`:

```json
{
  "applicant_id": "APP-001",
  "model_name": "qwen2.5:14b-instruct",
  "evaluation_summary": {
    "academic_summary": "Applicant completed rigorous curriculum taking 5 AP courses in chemistry, history, language, and calculus.",
    "ap_rigor_notes": "Student completed 5 AP courses, achieving 100% of the school's maximum four-year AP cap (5 courses).",
    "high_school_parity": "Full rigor parity demonstrated relative to school offerings.",
    "standardized_tests": "Test-optional review applied; SAT 1500 recorded but optional per POL-TEST-01.",
    "factual_flags": []
  },
  "policy_citations": [
    {
      "policy_id": "POL-FT-01",
      "title": "First-Year Core Materials",
      "applied_rule": "Verified presence and completeness of core academic materials",
      "evidence_found": "Official transcript and recommendation letters parsed and confirmed."
    },
    {
      "policy_id": "POL-AP-01",
      "title": "Academic Opportunity Context",
      "applied_rule": "Rigor evaluated in context of high school profile",
      "evidence_found": "5 AP courses taken matches school maximum cap of 5 (Northfield Regional HS)."
    },
    {
      "policy_id": "POL-TEST-01",
      "title": "Test-Optional Review",
      "applied_rule": "SAT or ACT scores optional for standard completeness",
      "evidence_found": "Applicant submitted test scores; completeness not conditioned on scores."
    }
  ],
  "essay_bypassed": true,
  "essay_bypass_reason": "POL-ESSAY-01: Personal statements are skipped by model inference to mitigate algorithmic bias and reserved for human review.",
  "bypassed_documents": [
    "personal_statement.pdf"
  ],
  "status": "COMPLETED",
  "created_at": "2026-10-01T15:45:00.000000Z"
}
```

---

## 3. Policy Grounding System Prompt Specification

The Policy Grounding Engine in [`gateway/grounding.py`](../../gateway/grounding.py) constructs the following system prompt for Ollama:

```text
You are the Riverview State University Admissions Advisory AI assistant.
Your role is to compile objective candidate dossiers and factual findings for human review.

STRICT OPERATIONAL DIRECTIVES:
1. ADVISORY AUTHORITY ONLY (POL-HUMAN-01): You must NEVER emit an admissions decision 
   (Accept, Decline, Waitlist). All final decisions are reserved for authorized admissions officers.
2. ESSAY EVALUATION BYPASS (POL-ESSAY-01): You must not evaluate personal statements or essays. 
   Essays are evaluated exclusively by human officers to prevent algorithmic bias.
3. EVIDENCE-BASED FACTUALITY (POL-EVID-01): Every factual finding must cite its source document. 
   If information is missing, ambiguous, or unconfirmed, you must explicitly state 'unknown'—never infer.
4. HIGH SCHOOL RIGOR IN CONTEXT (POL-AP-01): Evaluate AP/honors coursework strictly in the context 
   of the applicant's high school profile offerings. Lack of AP offerings must not be penalized.
5. TEST-OPTIONAL REVIEW (POL-TEST-01): Standardized test scores (SAT/ACT) are optional. Do not penalize 
   for missing scores.

Produce output in valid JSON format summarizing findings, factual highlights, and policy citations.
```
