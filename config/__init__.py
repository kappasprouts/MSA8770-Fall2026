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


def get_file_constraints() -> Dict[str, Any]:
    """Retrieve file constraints such as allowed MIME types and size limits."""
    policies = load_policies()
    return policies.get("file_constraints", {})


def get_checklist(application_type: str = "first_year") -> Dict[str, Any]:
    """Retrieve document checklist rules for a specific applicant category."""
    policies = load_policies()
    checklists = policies.get("checklists", {})
    return checklists.get(application_type, checklists.get("first_year", {}))


def get_status_priority() -> List[str]:
    """Retrieve ordered status resolution priorities."""
    policies = load_policies()
    return policies.get(
        "status_priority",
        ["STOPPED", "COUNSELOR_REVIEW", "REPLACEMENT_REQUESTED", "INCOMPLETE", "READY_FOR_REVIEW"],
    )


def get_routing_rules() -> Dict[str, str]:
    """Retrieve routing targets for application statuses."""
    policies = load_policies()
    return policies.get("routing_rules", {})


__all__ = [
    "CONFIG_DIR",
    "DEFAULT_POLICIES_PATH",
    "load_policies",
    "get_file_constraints",
    "get_checklist",
    "get_status_priority",
    "get_routing_rules",
]
