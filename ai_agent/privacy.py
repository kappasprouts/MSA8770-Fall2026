"""Conservative text-layer redaction before rendering model-bound pages."""

import re
import pymupdf

RESTRICTED_LABELS = {
    "date of birth", "dob", "mailing address", "primary phone number", "phone number",
    "email address", "email", "gender", "ethnicity", "hooks", "additional applicant context",
}
BOUNDARIES = RESTRICTED_LABELS | {
    "app id", "first name", "last name", "country", "region", "name of hs", "counselor name",
    "intended major", "admission year", "admission term", "unweighted gpa", "weighted gpa",
    "rank", "superscored sat score", "superscored act score", "ap courses", "total aps",
    "ib courses", "total ibs", "activities", "awards", "education", "academic interest statement",
    "applicant reported activities", "applicant reported awards",
}


def field_name(text):
    # Recognize both a standalone label and an inline "Label: value".
    return text.split(":", 1)[0].strip().casefold()


def restricted_pattern(value):
    digits = re.sub(r"\D", "", value)
    if len(digits) in {10, 11} and re.fullmatch(r"[\d\s()+.-]+", value):
        return r"(?<!\d)" + r"[\s()+.-]*".join(digits) + r"(?!\d)"
    return r"(?<!\w)" + r"\s+".join(re.escape(word) for word in value.split()) + r"(?!\w)"


def redact_fields(page, labels=RESTRICTED_LABELS):
    lines = [{"text": "".join(s["text"] for s in line["spans"]).strip(), "rect": pymupdf.Rect(line["bbox"])}
             for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])]
    lines = [line for line in lines if line["text"]]
    found = [line for line in lines if field_name(line["text"]) in labels]
    for line in found:
        start = line["rect"].y0
        # Include same-row values and all continuation lines until the next
        # recognized field/section. With no safe boundary, withhold the remainder.
        end = min((other["rect"].y0 for other in lines
                   if other["rect"].y0 > start + 2 and field_name(other["text"]) in BOUNDARIES),
                  default=page.rect.height)
        page.add_redact_annot(pymupdf.Rect(0, start - 1, page.rect.width, end - 1))
    if found:
        page.apply_redactions()
    if any(field_name(line) in labels for line in page.get_text().splitlines()):
        raise ValueError("Restricted field redaction could not be verified; human review required")
    return bool(found)


def redact_known_values(page, values):
    text = page.get_text()
    targets = list(values or [])
    targets.extend(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
    removed = []
    for value in targets:
        expression = restricted_pattern(value)
        for match in re.finditer(expression, text, re.IGNORECASE):
            rects = page.search_for(match[0])
            if not rects:
                raise ValueError("Cannot safely locate restricted value; human review required")
            for rect in rects:
                page.add_redact_annot(rect)
            removed.append(expression)
    if removed:
        page.apply_redactions()
    remaining = page.get_text()
    if any(re.search(expression, remaining, re.IGNORECASE) for expression in removed):
        raise ValueError("Restricted value remains after redaction; human review required")
