"""Structural and targeted numeric evidence validation, without model calls."""

from decimal import Decimal
import math
import re
import unicodedata

from jsonschema import Draft202012Validator


def schema_errors(schema, output):
    # Validator messages can echo the rejected instance. Keep retry feedback
    # limited to paths and trusted schema constraints, not applicant content.
    errors = []
    for error in Draft202012Validator(schema).iter_errors(output):
        expected = repr(error.validator_value) if error.validator in {"type", "enum", "minimum", "maximum", "minLength", "required"} else "no additional fields"
        errors.append(f"Schema {'.'.join(map(str, error.absolute_path)) or 'output'}: invalid {error.validator}; expected {expected}")
    # JSON does not have NaN/Infinity, although Python's decoder accepts them.
    def finite(node, path="output"):
        if isinstance(node, float) and not math.isfinite(node):
            errors.append(f"Schema {path}: number must be finite")
        elif isinstance(node, dict):
            for key, value in node.items():
                finite(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                finite(value, f"{path}[{i}]")
    finite(output)
    return errors


def tokens(text):
    text = unicodedata.normalize("NFKC", str(text)).lower().replace("\u00ad", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return re.findall(r"\d+(?:\.\d+)?|[^\W\d_]+", text, re.UNICODE)


def quote_matches(quote, page):
    expected, actual = tokens(quote), tokens(page)
    return bool(expected) and any(actual[i:i + len(expected)] == expected
                                  for i in range(len(actual) - len(expected) + 1))


METRIC_LABELS = {
    "unweighted_gpa": r"(?:unweighted gpa|gpa unweighted)",
    "weighted_gpa": r"(?:weighted gpa|gpa weighted)",
    "sat_superscore": r"(?:superscored sat(?: score)?|sat(?: superscore| score| total| composite)?)",
    "act_superscore": r"(?:superscored act(?: score)?|act(?: superscore| score| total| composite)?)",
}


def academic_fact_errors(output):
    errors = []
    for field, label in METRIC_LABELS.items():
        value = output["document_facts"].get(field)
        if value is None:
            continue
        supported = False
        for item in output["evidence"]:
            if item.get("verification_status") not in {"TEXT_VERIFIED", "UNVERIFIED_IMAGE_SOURCE"}:
                continue
            passage = " ".join(tokens(item["quote"]))
            matches = re.finditer(rf"\b{label}\b (\d+(?:\.\d+)?)\b", passage)
            if any(Decimal(match[1]) == Decimal(str(value)) for match in matches):
                supported = True
                break
        if not supported:
            errors.append(f"document_facts.{field}: needs a cited quotation pairing the correct metric label with value {value}.")
    return errors
