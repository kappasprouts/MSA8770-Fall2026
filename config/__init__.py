"""Configuration package for Riverview State University admissions pipeline.

Loads validation rules, checklist policies, size limits, and operational policies.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

try:
    from dotenv import load_dotenv
    # Load .env from repository root if present
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_POLICIES_PATH = CONFIG_DIR / "policies.yaml"


def load_policies(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load policy rules from the YAML configuration file."""
    config_file = path or DEFAULT_POLICIES_PATH
    if not config_file.exists():
        raise FileNotFoundError(f"Policy configuration file not found at: {config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_file_constraints(path: Optional[Path] = None) -> Dict[str, Any]:
    """Retrieve file constraints such as allowed MIME types and size limits."""
    policies = load_policies(path)
    return policies.get("file_constraints", {})


def get_checklist(application_type: str = "first_year", path: Optional[Path] = None) -> Dict[str, Any]:
    """Retrieve document checklist rules for a specific applicant category."""
    policies = load_policies(path)
    checklists = policies.get("checklists", {})
    return checklists.get(application_type, checklists.get("first_year", {}))


def get_required_applicant_fields(path: Optional[Path] = None) -> List[str]:
    """Retrieve required applicant metadata fields from CSV schema."""
    policies = load_policies(path)
    return policies.get("required_applicant_fields", [
        "App_ID",
        "First_Name",
        "Last_Name",
        "Date_Of_Birth",
        "Email_Address",
    ])


def get_status_priority(path: Optional[Path] = None) -> List[str]:
    """Retrieve ordered status resolution priorities."""
    policies = load_policies(path)
    return policies.get(
        "status_priority",
        ["ERROR", "STOPPED", "COUNSELOR_REVIEW", "REPLACEMENT_REQUESTED", "INCOMPLETE", "AWAITING_MATERIALS", "VALID", "READY_FOR_REVIEW"],
    )


def get_routing_rules(path: Optional[Path] = None) -> Dict[str, str]:
    """Retrieve routing targets for application statuses."""
    policies = load_policies(path)
    return policies.get("routing_rules", {})


def derive_routing_destination(status: str, rules: Optional[Dict[str, str]] = None) -> str:
    """Compute the current queue from a workflow status without storing it."""
    targets = rules if rules is not None else get_routing_rules()
    status_value = getattr(status, "value", status)
    if status_value in {"READY_FOR_REVIEW", "VALID"}:
        return targets.get("on_valid", targets.get("on_ready", "READY_FOR_REVIEW"))
    if status_value == "INCOMPLETE":
        return targets.get("on_incomplete", "Applicant Packet Update")
    if status_value == "AWAITING_MATERIALS":
        return targets.get("on_awaiting_materials", targets.get("on_incomplete", "Applicant Packet Update"))
    if status_value == "PENDING":
        return "PENDING"
    if status_value == "ERROR":
        return targets.get("on_error", targets.get("on_invalid", "Human Review"))
    return targets.get("on_invalid", targets.get("on_error", "Human Review"))


__all__ = [
    "CONFIG_DIR",
    "DEFAULT_POLICIES_PATH",
    "load_policies",
    "get_file_constraints",
    "get_checklist",
    "get_required_applicant_fields",
    "get_status_priority",
    "get_routing_rules",
    "derive_routing_destination",
]
