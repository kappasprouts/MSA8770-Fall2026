"""Allowlisted current score facts and input-quality checks, before inference."""

SCORE_RANGES = {
    "superscored_sat_score": (400, 1600), "sat_math": (200, 800), "sat_ebrw": (200, 800),
    **{name: (1, 36) for name in (
        "superscored_act_score", "act_composite", "act_english", "act_math", "act_reading", "act_science",
    )},
    "act_writing": (2, 12),
}


def current_test_scores(applicant):
    """Return source-qualified facts and errors without changing the source row.

    The active schema does not retain per-field feed origin/time. Identify the
    database snapshot honestly; never label it an official testing-agency report.
    AP course-name strings are coursework, not evidence of an exam score.
    """
    stamp = applicant.get("updated_at")
    source = {
        "system": "PostgreSQL", "table": "applicants", "app_id": applicant.get("app_id"),
        "record_updated_at": stamp.isoformat() if hasattr(stamp, "isoformat") else stamp,
        "feed_origin": "not recorded at field level",
    }
    facts, issues = {}, []

    def error(field, value, message):
        issues.append({"field": field, "value": value, "message": message, "source": {**source, "field": field}})

    for field, (low, high) in SCORE_RANGES.items():
        value = applicant.get(field)
        if value is not None and (type(value) is not int or not low <= value <= high):
            error(field, value, f"{field}: expected an integer from {low} to {high}; correction required.")
        facts[field] = {"value": value, "source": {**source, "field": field}}

    ap_courses, ap_scores = [], []
    records = applicant.get("ap_test_scores")
    if records is None:
        records = []
    if not isinstance(records, list):
        error("ap_test_scores", records, "ap_test_scores: expected a list; correction required.")
        records = []
    for index, item in enumerate(records):
        field = f"ap_test_scores[{index}]"
        provenance = {**source, "field": field}
        if isinstance(item, str) and item.strip():
            ap_courses.append({"course": item.strip(), "source": provenance})
        elif isinstance(item, dict):
            subject, score = item.get("subject"), item.get("score")
            if not isinstance(subject, str) or not subject.strip():
                error(field, item, f"{field}: AP subject is required; correction required.")
            elif score is None:
                ap_courses.append({"course": subject.strip(), "source": provenance})
            elif type(score) is not int or not 1 <= score <= 5:
                error(field, item, f"{field}: AP score must be an integer from 1 to 5; correction required.")
            else:
                ap_scores.append({"subject": subject.strip(), "score": score, "source": provenance})
        else:
            error(field, item, f"{field}: expected a course name or subject/score record; correction required.")
    return {"scores": facts, "ap_courses": ap_courses, "ap_exam_scores": ap_scores}, issues
