"""Date normalization shared by applicant ingestion and score-feed matching."""

from datetime import date, datetime
from typing import Any, Optional

DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
)

def parse_date_of_birth(value: Any) -> Optional[date]:
    """Return a real date, preserving the formats accepted by score matching."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = str(value).strip()
    if not raw or raw.lower() == "nan":
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date of birth: {raw!r}")
