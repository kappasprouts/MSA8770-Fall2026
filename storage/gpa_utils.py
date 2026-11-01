"""Shared two-decimal GPA normalization for CSV and direct storage writes."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_gpa(value):
    if value is None or str(value).strip().lower() in {"", "nan"}:
        return None
    try:
        number = Decimal(str(value).strip())
        return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if number.is_finite() else None
    except InvalidOperation:
        return None
