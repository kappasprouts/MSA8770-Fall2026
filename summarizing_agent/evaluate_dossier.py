"""
evaluate_dossier.py

Score a dossier (results/<APP_ID>_dossier.json) against its answer key
(answer_keys/<APP_ID>.json). Scores SUMMARY ACCURACY only: facts,
coverage, details, citations, and leaks.

    python evaluate_dossier.py APP_001
    python evaluate_dossier.py APP_001 | tee results/scorecard.txt
"""

import json
import re
import sys
from pathlib import Path

import pymupdf

from summarizing_agent import quote_on_page


ROOT = Path(__file__).resolve().parent


def norm(text):
    return re.sub(r"[^a-z0-9.+]", "", str(text).lower().replace("–", "-"))


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return norm(a) == norm(b)


def tick(ok):
    return "✓" if ok else "✗"


def main():

    app_id = sys.argv[1] if len(sys.argv) > 1 else "APP_001"

    record = json.loads((ROOT / "results" / f"{app_id}_dossier.json").read_text())
    key = json.loads((ROOT / "answer_keys" / f"{app_id}.json").read_text())

    run, dossier = record["run"], record.get("applicant_dossier")

    print("========================================")
    print(f"DOSSIER EVALUATION: {app_id}")
    print("========================================")
    print(f"Status: {run['run_status']}   model calls: {run['attempts']}   time: {run['runtime_seconds']}s")

    for call in (run.get("validation") or {}).get("calls", []):
        usage = call.get("usage") or {}
        result = "passed" if not call["errors"] else f"{len(call['errors'])} problem(s)"
        print(f"  {call['section']:<15} attempt {call['attempt']}: {usage.get('seconds', '-')}s, "
              f"{usage.get('output_tokens', '-')} tokens → {result}")

    if not dossier:
        print("\nNo dossier was saved; nothing to score.")
        return

    scores = {}
    academic = dossier["academic_profile"]
    engagement = dossier["engagement_profile"]

    # ---- Facts ------------------------------------------------------------
    print("\nFACTS (read from the documents)")
    facts = academic.get("document_facts") or {}
    correct = 0
    for field, expected in key["document_facts"].items():
        ok = same(facts.get(field), expected)
        correct += ok
        print(f"  {tick(ok)} {field:<20} got={facts.get(field)!s:<28} expected={expected}")
    scores["Facts correct"] = (correct, len(key["document_facts"]))

    # ---- AP courses on transcript ------------------------------------------
    print("\nAP COURSES ON TRANSCRIPT (course, grade level, final grade)")
    got = {norm(c["course"]): c for c in academic.get("ap_courses_on_transcript", [])}
    correct = 0
    for expected in key["ap_courses_on_transcript"]:
        found = got.get(norm(expected["course"]))
        ok = bool(found) and same(found["grade_level"], expected["grade_level"]) and same(found["final_grade"], expected["final_grade"])
        correct += ok
        detail = f"got {found['grade_level']}/{found['final_grade']}" if found else "missing"
        print(f"  {tick(ok)} {expected['course']:<24} expected {expected['grade_level']}/{expected['final_grade']}  {detail}")
    invented = sorted(c["course"] for k, c in got.items()
                      if k not in {norm(e["course"]) for e in key["ap_courses_on_transcript"]})
    print(f"  invented (not AP on transcript): {invented or 'none'}")
    scores["AP courses (transcript)"] = (correct, len(key["ap_courses_on_transcript"]))
    scores["Invented AP courses"] = (len(invented), None)

    # ---- AP exam scores -----------------------------------------------------
    print("\nAP EXAM SCORES (course, score, date)")
    got = {norm(s["course"]): s for s in academic.get("ap_exam_scores", [])}
    correct = 0
    for expected in key["ap_exam_scores"]:
        found = got.get(norm(expected["course"]))
        ok = bool(found) and same(found["score"], expected["score"]) and same(found["date"], expected["date"])
        correct += ok
        print(f"  {tick(ok)} {expected['course']:<24} expected {expected['score']}, {expected['date']}  "
              f"{'got ' + found['score'] + ', ' + found['date'] if found else 'missing'}")
    scores["AP exam scores"] = (correct, len(key["ap_exam_scores"]))

    # ---- Activities -----------------------------------------------------------
    print("\nACTIVITIES (name, years, hours/week)")
    got = engagement.get("activities", [])
    named = details = 0
    for expected in key["activities"]:
        found = next((a for a in got if norm(expected["activity"].split()[0]) in norm(a["activity"])
                      and norm(" ".join(expected["activity"].split()[:2])) in norm(a["activity"])), None)
        named += bool(found)
        ok = bool(found) and same(found["years"], expected["years"]) and same(found["hours_per_week"], expected["hours_per_week"])
        details += ok
        detail = f"got {found['years']}, {found['hours_per_week']}" if found else "missing"
        print(f"  {tick(ok)} {expected['activity']:<28} expected {expected['years']}, {expected['hours_per_week']}  {detail}")
    scores["Activities named"] = (named, len(key["activities"]))
    scores["Activity details correct"] = (details, len(key["activities"]))

    # ---- Awards ---------------------------------------------------------------
    got = {norm(a) for a in engagement.get("awards", [])}
    found = [a for a in key["awards"] if norm(a) in got]
    extra = [a for a in engagement.get("awards", []) if norm(a) not in {norm(k) for k in key["awards"]}]
    print(f"\nAWARDS  {len(found)}/{len(key['awards'])} exact   extra/changed: {extra or 'none'}")
    scores["Awards exact"] = (len(found), len(key["awards"]))

    # ---- Recommenders -----------------------------------------------------------
    recommenders = dossier["recommendation_profile"].get("recommenders", [])
    correct = sum(
        1 for expected in key["recommenders"]
        if any(expected["name"].split()[-1].lower() in r["name"].lower()
               and expected["role"].split()[-1].lower() in r["role"].lower() for r in recommenders)
    )
    print(f"\nRECOMMENDERS  {correct}/{len(key['recommenders'])} with correct name and role")
    scores["Recommenders"] = (correct, len(key["recommenders"]))

    # ---- Supplement ---------------------------------------------------------------
    prompts = [norm(r["prompt"]) for r in dossier["supplemental_essay_profile"].get("responses", [])]
    correct = sum(1 for p in key["supplement_prompts"] if any(norm(p) in g or g in norm(p) for g in prompts))
    print(f"SUPPLEMENT    {correct}/{len(key['supplement_prompts'])} questions summarized")
    scores["Supplement questions"] = (correct, len(key["supplement_prompts"]))

    # ---- Citations: re-checked independently against the PDFs ------------------------
    pdf_dir = ROOT / "data" / "sample_docs" / app_id
    grounded = 0
    for item in dossier["evidence_map"]:
        try:
            text = pymupdf.open(pdf_dir / item["document"])[item["page"] - 1].get_text()
            grounded += quote_on_page(item["quote"], text)
        except Exception:
            pass
    print(f"\nCITATIONS     {grounded}/{len(dossier['evidence_map'])} quotes found on the cited page")
    scores["Citations grounded"] = (grounded, len(dossier["evidence_map"]))

    # ---- Leaks ------------------------------------------------------------------------
    model_text = json.dumps({k: v for k, v in dossier.items() if k != "applicant_demographics"}).lower()
    leaks = [v for v in key["must_not_appear"] if v.lower() in model_text]
    print(f"RESTRICTED DATA LEAKS  {leaks or 'none'}")
    scores["Restricted data leaks"] = (len(leaks), None)

    # ---- Scorecard ---------------------------------------------------------------------
    print("\nSCORECARD")
    for name, (value, total) in scores.items():
        print(f"  {name:<26} {value}/{total}" if total is not None else f"  {name:<26} {value}")


if __name__ == "__main__":
    main()
