# Reference Run: APP_001

The run made while building this agent, for testers to compare against.

| | |
|---|---|
| Date | 2026-10-06 |
| Machine | MacBook, Apple M4, 16 GB RAM, Chrome closed |
| Model | `qwen3-vl:8b-instruct` (Ollama), temperature 0 |
| Embeddings | `nomic-embed-text` |
| Pages | 1.5× render, context 16,384 tokens |
| Result | **DOSSIER_READY**, saved to `applicant_dossier` |
| Total time | **10.3 min** (618 s) |

Files in this folder:

- `run_output.txt`: full screen output (setup 1–3 and the agent)
- `APP_001_dossier.json`: the run record and the dossier
- `scorecard.txt`: output of `evaluate_dossier.py`

---

## Pipeline steps

| Step | Result |
|---|---|
| [1] Load | APP_001, status COMPLETE, 10 documents listed |
| [2] Withhold | `personal_statement.pdf` (POL-ESSAY-01), `common_app_application.pdf` (restricted data) |
| [3] Pages | 8 PDFs → 10 page images |
| [4] RAG | 8 policies: POL-DATE-01, POL-ESSAY-01, POL-FT-01, POL-HUMAN-01, POL-ID-01, POL-LOR-01, POL-READ-01, POL-TEST-01 (international and transfer rules filtered out) |
| [5]+[6] Sections | see below |
| [7] Assemble | 29 citations in `evidence_map`, 0 review notes |
| [8] Save | `applicant_dossier`, `dossier_generation_runs`, `summary_audit_log`, JSON file; status → DOSSIER_READY |

| Section | Pages | Time | Output tokens | Validation |
|---|---|---|---|---|
| academic | 5 | 132 s + 67 s | 1,089 / 939 | ✗ then ✓ (retried once) |
| engagement | 2 | 105 s | 1,055 | ✓ |
| recommendation | 2 | 72 s | 598 | ✓ |
| supplement | 1 | 50 s | 504 | ✓ |
| policy (RAG) | text | 119 s | 1,067 | ✓ |
| synthesis | text | 73 s | 441 | ✓ |

**The retry:** the first academic answer cited *"AP Computer Science A 11 A"*
on the AP record page. No such row exists (the AP record shows a score of 3,
not a grade). The citation check rejected it and the retry passed.

---

## Accuracy (scorecard)

| Measure | Score |
|---|---|
| Facts (GPA ×2, class rank, SAT, ACT, major, school, graduation) | **8/8** |
| Activities named | **9/9** |
| Activity details (years, hours/week) | **9/9** |
| Awards, exact | **5/5** |
| Recommenders (name and role) | **2/2** |
| Supplement questions summarized | **3/3** |
| AP exam scores (course, score, date) | 6/7 (missed AP Computer Science A) |
| AP courses on the transcript (course, grade level, grade) | **2/5** |
| AP courses wrongly listed as on the transcript | **2** (AP Microeconomics, AP Physics C Mechanics) |
| Citations whose quote is on the cited page | **29/29** |
| Restricted data in output (gender, ethnicity, DOB, contact) | **0** |
| Admission-decision wording | none |

---

## Issues found by reading the dossier

Things the automatic checks do not catch:

1. **Transcript AP list is wrong.** The model mixed the AP record into the
   transcript list: it added two courses that are only on the AP record, missed
   AP English Language (grade 11, B+), and gave AP Human Geography and AP
   Spanish Language grade 11 instead of 12. These list fields have no quotes,
   so the citation check cannot catch them.
2. **Gendered pronoun.** The recommendation summary calls the applicant "his".
   The documents the model saw contain no gender; it guessed from the name
   "Alex". Gender is restricted data, so the summary should say "the applicant"
   or "they". The restricted-data check looks for the stored values (e.g.
   "Female"), not pronouns.
3. **Judgments beyond summarizing.** An academic "concern" says the SAT score
   "may not be sufficient for highly competitive programs", and the holistic
   assessment says all documents "meet required submission standards". Neither
   is an admission decision, but both go beyond what the documents say.
4. **Policy assessment is thin.** Three policies are marked `not_applicable`
   because the policy call sees only the section summaries, not the files
   (e.g. POL-READ-01 readability, POL-ID-01 ID matching).
5. **Applicant record typo.** `applicant_demographics.intended_major` is
   "Studio Art, llustration" because that is how it appears in the CSV. The
   documents say "Illustration", and the model read that correctly.

## Possible improvements

- Give the transcript AP list its own instruction or call (transcript pages
  only), separate from the AP record.
- Add "refer to the applicant as 'the applicant' or 'they'" to the rules, and a
  code check for gendered pronouns.
- Tell the model not to add comparative judgments in `concerns` and
  `holistic_assessment`.
- Give the policy call the list of withheld and loaded documents with their
  load status, so readability and ID-matching policies can be assessed.

---

## Compared with earlier versions

| | Starting point (Run 1) | First full dossier (one call) | **This agent** |
|---|---|---|---|
| Documents seen | 4 (incl. Common App) | 8 | 8 (Common App withheld) |
| Restricted data sent to model | yes | no | no |
| Facts correct | GPA only checked | 7/9 | **8/8** |
| Activities with correct details | not checked | 4/9 | **9/9** |
| Awards | 5/5 (copied from Common App) | 5/5 | **5/5** |
| Invented AP courses | 2 | 1 on transcript | 2 on transcript |
| Citations grounded | not checked | 72/82 (88%) | **29/29 (100%)** |
| Dossier saved to PostgreSQL | no | yes | yes |
| Time | 5 min | 11.5 min (Chrome open) | 10.3 min |
