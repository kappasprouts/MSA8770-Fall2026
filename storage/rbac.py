"""Role-Based Access Control (RBAC) Module for Riverview Admissions Pipeline.

Enforces role-based permissions across admissions pipeline operations,
matching the policy matrix in ui/src/lib/auth-policy.ts and system_users_schema.sql:

Roles:
- ADMISSIONS_OFFICER:
    * Allowed: processing (batch ingestion), review (applicant review & recommendation), statistics
    * Blocked: decisions (cannot post final accept/waitlist/decline), errors (IT exception queue)
- DEAN:
    * Allowed: review (viewing dossiers), decisions (authoritative final admission decisions), statistics
    * Blocked: processing (raw ingestion), errors (IT exception queue)
- IT_SUPPORT / IT_ADMIN:
    * Allowed: errors (IT exception/quarantine queue)
    * Blocked: processing, review (confidential applicant dossiers), decisions (admissions outcomes)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Applicant, AuditLog, SystemUser

logger = logging.getLogger(__name__)


class Role(str, Enum):
    ADMISSIONS_OFFICER = "ADMISSIONS_OFFICER"
    DEAN = "DEAN"
    IT_SUPPORT = "IT_SUPPORT"
    IT_ADMIN = "IT_ADMIN"


class Permission(str, Enum):
    PROCESSING = "processing"
    REVIEW = "review"
    DECISIONS = "decisions"
    STATISTICS = "statistics"
    ERRORS = "errors"


ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "ADMISSIONS_OFFICER": {"processing", "review", "statistics"},
    "DEAN": {"review", "decisions", "statistics"},
    "IT_SUPPORT": {"errors"},
    "IT_ADMIN": {"errors"},
}

ALLOWED_DECISIONS = {"ACCEPT", "WAITLIST", "DECLINE"}


def can_access(role: Optional[str], permission: str) -> bool:
    """Check if a given role possesses the specified permission."""
    if not role:
        return False
    return permission in ROLE_PERMISSIONS.get(role, set())


def enforce_permission(role: Optional[str], permission: str, actor_id: str = "unknown") -> None:
    """Raise PermissionError if role is not authorized for the requested permission."""
    if not can_access(role, permission):
        msg = f"Access Denied: Role '{role}' (actor '{actor_id}') is not authorized for '{permission}'"
        logger.warning(msg)
        raise PermissionError(msg)


def apply_final_decision(
    storage: Any,
    applicant_id: str,
    decision: str,
    user_role: str,
    user_id: str = "anonymous",
) -> bool:
    """Apply an authoritative admissions decision to an applicant record.

    Only the DEAN role possesses the 'decisions' permission.
    Unauthorized attempts (e.g., ADMISSIONS_OFFICER or IT_SUPPORT) are blocked,
    logged in audit_logs, and leave the applicant database record unchanged.
    """
    decision_clean = str(decision).upper().strip()
    if decision_clean not in ALLOWED_DECISIONS:
        raise ValueError(f"Invalid decision '{decision}'. Must be one of {ALLOWED_DECISIONS}")

    # Enforce RBAC
    if not can_access(user_role, "decisions"):
        # Log unauthorized attempt to audit_logs
        if hasattr(storage, "log_audit"):
            storage.log_audit(
                applicant_id=applicant_id,
                action="UNAUTHORIZED_DECISION_BLOCKED",
                actor=user_id,
                details={
                    "attempted_role": user_role,
                    "attempted_decision": decision_clean,
                    "reason": "Role lacks 'decisions' permission (DEAN only)",
                },
            )
        msg = f"Forbidden: Role '{user_role}' is not authorized to finalize admissions decisions. Only DEAN may decide."
        logger.warning(msg)
        raise PermissionError(msg)

    # Authorized (DEAN): Mutate database row
    if storage.db_available and storage.SessionLocal:
        session: Session = storage.SessionLocal()
        try:
            applicant = session.execute(
                select(Applicant).where(Applicant.app_id == applicant_id)
            ).scalar_one_or_none()
            if not applicant:
                return False
            previous_decision = applicant.final_decision
            applicant.final_decision = decision_clean
            applicant.updated_at = datetime.now(timezone.utc)

            # Insert immutable audit trail
            session.add(
                AuditLog(
                    applicant_id=applicant_id,
                    action="FINAL_DECISION_RECORDED",
                    actor=user_id,
                    details={
                        "role": user_role,
                        "previous_decision": previous_decision,
                        "final_decision": decision_clean,
                    },
                )
            )
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error("Failed to commit final decision: %s", e)
            raise
        finally:
            session.close()

    # Dry-run fallback
    if applicant_id in getattr(storage, "dry_run_applicants", {}):
        storage.dry_run_applicants[applicant_id].final_decision = decision_clean
        return True

    return False


def get_applicant_dossier_review(
    storage: Any,
    applicant_id: str,
    user_role: str,
    user_id: str = "anonymous",
) -> Optional[Dict[str, Any]]:
    """Retrieve applicant dossier for review.

    Requires 'review' permission (ADMISSIONS_OFFICER or DEAN).
    Unauthorized roles (e.g., IT_SUPPORT / IT_ADMIN) are strictly blocked.
    """
    if not can_access(user_role, "review"):
        if hasattr(storage, "log_audit"):
            storage.log_audit(
                applicant_id=applicant_id,
                action="UNAUTHORIZED_DOSSIER_ACCESS_BLOCKED",
                actor=user_id,
                details={
                    "attempted_role": user_role,
                    "reason": "Role lacks 'review' permission",
                },
            )
        raise PermissionError(
            f"Forbidden: Role '{user_role}' is not authorized to review applicant dossiers."
        )

    applicant = storage.get_applicant(applicant_id)
    if not applicant:
        return None

    if hasattr(storage, "log_audit"):
        storage.log_audit(
            applicant_id=applicant_id,
            action="DOSSIER_REVIEW_ACCESSED",
            actor=user_id,
            details={"role": user_role},
        )

    return applicant.to_dict() if hasattr(applicant, "to_dict") else vars(applicant)
