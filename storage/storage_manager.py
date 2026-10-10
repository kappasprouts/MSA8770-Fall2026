"""Storage and MinIO connection manager for Riverview Admissions Pipeline.

Provides robust PostgreSQL and MinIO connection handlers, reading configuration
from environment variables (.env / os.environ). If PostgreSQL or MinIO connections
are unavailable, logs clear warnings and permits dry-run local manifest generation,
while performing real uploads and inserts when services are online.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
import urllib.parse

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.orm.attributes import flag_modified

try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_SDK_AVAILABLE = True
except ImportError:
    MINIO_SDK_AVAILABLE = False

from storage.database import Base
from storage.date_utils import parse_date_of_birth
from storage.models import (
    Applicant,
    AuditLog,
    DocumentRecord,
    OrphanDocument,
    OrphanTestScore,
)

logger = logging.getLogger(__name__)


def normalize_applicant_id(text: Optional[str]) -> Optional[str]:
    """Normalize applicant ID to canonical format (e.g., APP_001).

    Supports formats like APP_001, APP001, app_001, APP-001, app10, etc.
    """
    if not text:
        return None
    match = re.search(r"APP[_\-\s]?(\d+)", str(text), re.IGNORECASE)
    if match:
        digits = match.group(1)
        if len(digits) >= 3:
            return f"APP_{digits}"
        else:
            num = int(digits)
            return f"APP_{num:03d}"
    return None


def applicant_id_candidates(app_id: str) -> List[str]:
    """Return known spellings of an applicant ID, preferring the supplied spelling."""
    normalized = normalize_applicant_id(app_id)
    variants = [app_id, app_id.replace("-", "_"), app_id.replace("_", "-"), app_id.upper()]
    if normalized:
        variants.extend((normalized, normalized.replace("_", "-"), normalized.replace("_", "")))
    variants.extend(variant.lower() for variant in tuple(variants))
    return list(dict.fromkeys(variants))


class StorageManager:
    """Manages relational (PostgreSQL or persistent SQLite) and object storage (MinIO) interactions
    with automatic persistent local SQLite fallback when PostgreSQL is not reachable.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        minio_endpoint: Optional[str] = None,
        minio_access_key: Optional[str] = None,
        minio_secret_key: Optional[str] = None,
        minio_secure: Optional[bool] = None,
        minio_bucket: Optional[str] = None,
        sqlite_store_path: Optional[str] = None,
        use_sqlite_fallback: bool = True,
    ):
        # Database Configuration
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/riverview_admissions",
        )
        # Adapt postgresql:// to postgresql+psycopg:// if using psycopg v3
        if self.database_url.startswith("postgresql://") and not self.database_url.startswith("postgresql+"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

        self.sqlite_store_path = sqlite_store_path or os.getenv("SQLITE_STORE_PATH", "data/local/.local_dev_store.db")
        self.use_sqlite_fallback = use_sqlite_fallback
        self.is_sqlite_fallback = False

        # MinIO Configuration
        self.minio_endpoint = minio_endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.minio_access_key = minio_access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.minio_secret_key = minio_secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self.minio_secure = (
            minio_secure
            if minio_secure is not None
            else os.getenv("MINIO_SECURE", "false").lower() == "true"
        )
        self.minio_bucket = minio_bucket or os.getenv("MINIO_BUCKET", "admissions-raw-docs")

        # In-memory stores for dry-run mode
        self.dry_run_applicants: Dict[str, Applicant] = {}
        self.dry_run_orphans: List[OrphanDocument] = []
        self.dry_run_orphan_scores: List[OrphanTestScore] = []

        # Connect to Database
        self.db_available = False
        self.engine = None
        self.SessionLocal = None
        self._init_db_connection()

        # Connect to MinIO
        self.minio_available = False
        self.minio_client: Optional[Any] = None
        self._init_minio_connection()

    @staticmethod
    def _is_reachable(host: str, port: int, timeout: float = 0.2) -> bool:
        """Fast non-blocking probe to verify if remote port is listening."""
        import socket
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, ConnectionRefusedError):
            return False

    @staticmethod
    def _migrate_sqlite_applicants(engine) -> None:
        """Upgrade the persistent local fallback to the status-only model."""
        with engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(applicants)"))}
            if "ib_test_scores" not in columns:
                conn.execute(text("ALTER TABLE applicants ADD COLUMN ib_test_scores JSON NOT NULL DEFAULT '[]'"))
                if "ib_courses" in columns:
                    old_rows = conn.execute(text(
                        "SELECT app_id, ib_courses FROM applicants "
                        "WHERE ib_courses IS NOT NULL AND trim(ib_courses) <> ''"
                    ))
                    for app_id, courses in old_rows:
                        items = [item.strip() for item in courses.split(",") if item.strip()][:12]
                        conn.execute(
                            text("UPDATE applicants SET ib_test_scores = :items WHERE app_id = :app_id"),
                            {"items": json.dumps(items), "app_id": app_id},
                        )
            if "routing_destination" in columns:
                conn.execute(text("ALTER TABLE applicants DROP COLUMN routing_destination"))

    def _init_db_connection(self):
        """Attempt to establish PostgreSQL connection, falling back gracefully to persistent SQLite store."""
        # 1. Direct SQLite database URL requested
        if self.database_url.startswith("sqlite"):
            try:
                self.engine = create_engine(self.database_url, connect_args={"check_same_thread": False})
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.SessionLocal = sessionmaker(
                    autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine
                )
                Base.metadata.create_all(bind=self.engine)
                self._migrate_sqlite_applicants(self.engine)
                self.db_available = True
                self.is_sqlite_fallback = True
                logger.info("Successfully connected to SQLite database at: %s", self.database_url)
                return
            except Exception as e:
                logger.warning("Could not connect to specified SQLite database (%s).", e)

        # 2. Check PostgreSQL availability
        postgres_online = False
        host, port = "localhost", 5432
        try:
            parsed = urllib.parse.urlsplit(self.database_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            if self._is_reachable(host, port, timeout=0.2):
                postgres_online = True
        except Exception:
            postgres_online = False

        if postgres_online:
            try:
                self.engine = create_engine(self.database_url, pool_pre_ping=True)
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.SessionLocal = sessionmaker(
                    autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine
                )
                Base.metadata.create_all(bind=self.engine)
                self.db_available = True
                self.is_sqlite_fallback = False
                logger.info("Successfully connected to PostgreSQL at: %s", self._safe_url(self.database_url))
                return
            except Exception as e:
                logger.warning("PostgreSQL connection failed (%s). Falling back to persistent SQLite.", e)
        else:
            logger.info("Database host %s:%s is not reachable. Operating in persistent local SQLite mode.", host, port)

        # 3. Persistent Local SQLite Fallback
        if self.use_sqlite_fallback:
            try:
                db_path = Path(self.sqlite_store_path).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                sqlite_url = f"sqlite:///{db_path}"
                self.engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.SessionLocal = sessionmaker(
                    autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine
                )
                Base.metadata.create_all(bind=self.engine)
                self._migrate_sqlite_applicants(self.engine)
                self.db_available = True
                self.is_sqlite_fallback = True
                logger.info("Persistent local SQLite fallback initialized at: %s", db_path)
                return
            except Exception as e:
                logger.warning("Could not initialize local SQLite fallback store (%s).", e)

        # 4. Volatile In-Memory Fallback if SQLite fails
        self.db_available = False
        self.engine = None
        self.SessionLocal = None
        logger.warning("Operating in ephemeral dry-run in-memory mode.")

    def _init_minio_connection(self):
        """Attempt to establish MinIO client connection, falling back gracefully to dry-run."""
        if not MINIO_SDK_AVAILABLE:
            self.minio_available = False
            logger.warning("MinIO SDK not installed. Operating in dry-run local mode for object storage.")
            return

        # Fast probe for MinIO host/port reachability to avoid urllib3 retry loops
        try:
            parts = self.minio_endpoint.split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 9000
            if not self._is_reachable(host, port, timeout=0.2):
                self.minio_available = False
                logger.warning(
                    "MinIO endpoint %s:%d is not reachable. Operating in dry-run local mode for raw document archival.",
                    host,
                    port,
                )
                return
        except Exception:
            pass

        try:
            client = Minio(
                self.minio_endpoint,
                access_key=self.minio_access_key,
                secret_key=self.minio_secret_key,
                secure=self.minio_secure,
            )
            # Test connectivity by checking or creating bucket
            if not client.bucket_exists(self.minio_bucket):
                client.make_bucket(self.minio_bucket)
            self.minio_client = client
            self.minio_available = True
            logger.info("Successfully connected to MinIO at %s (bucket: %s)", self.minio_endpoint, self.minio_bucket)
        except Exception as e:
            self.minio_available = False
            self.minio_client = None
            logger.warning(
                "Could not connect to MinIO at %s (%s). Operating in dry-run local mode for raw document archival.",
                self.minio_endpoint,
                str(e),
            )

    def _safe_url(self, url: str) -> str:
        """Mask credentials from connection URL for safe logging."""
        try:
            parsed = urllib.parse.urlsplit(url)
            if parsed.password:
                netloc = f"{parsed.username}:***@{parsed.hostname}:{parsed.port}"
                return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        except Exception:
            pass
        return url

    def ensure_bucket_exists(self, bucket_name: Optional[str] = None) -> bool:
        """Ensure designated bucket exists in MinIO."""
        target_bucket = bucket_name or self.minio_bucket
        if not self.minio_available or not self.minio_client:
            logger.debug("[Dry-Run MinIO] Verified bucket exists: '%s'", target_bucket)
            return True

        try:
            if not self.minio_client.bucket_exists(target_bucket):
                self.minio_client.make_bucket(target_bucket)
                logger.info("Created MinIO bucket: '%s'", target_bucket)
            return True
        except Exception as e:
            logger.warning("Error checking/creating bucket '%s': %s", target_bucket, e)
            return False

    def upload_file(
        self,
        file_path: Path,
        minio_key: str,
        bucket_name: Optional[str] = None,
        content_type: str = "application/pdf",
    ) -> str:
        """Upload raw document file to MinIO object storage.

        If MinIO is offline, logs simulated upload and returns expected key.
        """
        target_bucket = bucket_name or self.minio_bucket
        path = Path(file_path)

        if not self.minio_available or not self.minio_client:
            logger.debug("[Dry-Run MinIO] Simulated upload: %s -> s3://%s/%s", path.name, target_bucket, minio_key)
            return minio_key

        try:
            self.minio_client.fput_object(
                bucket_name=target_bucket,
                object_name=minio_key,
                file_path=str(path),
                content_type=content_type,
            )
            logger.info("Uploaded to MinIO: s3://%s/%s (%d bytes)", target_bucket, minio_key, path.stat().st_size)
            return minio_key
        except Exception as e:
            logger.exception("MinIO upload failed for %s", minio_key)
            raise RuntimeError(f"MinIO upload failed for {minio_key}") from e

    def object_exists(self, minio_key: str, bucket_name: Optional[str] = None) -> bool:
        """Confirm a linked document is retrievable before production handoff."""
        if not minio_key or not self.minio_available or not self.minio_client:
            return False
        try:
            self.minio_client.stat_object(bucket_name or self.minio_bucket, minio_key)
            return True
        except Exception as exc:
            logger.warning("MinIO object is unavailable: s3://%s/%s (%s)", bucket_name or self.minio_bucket, minio_key, exc)
            return False

    def stage_applicant(
        self, applicant_data: Dict[str, Any], update_fields: Optional[Set[str]] = None
    ) -> Applicant:
        """Stage or upsert an applicant, optionally limiting fields updated on an existing row."""
        applicant_data = dict(applicant_data)
        # Serialized applicants may expose this derived value for API callers.
        applicant_data.pop("routing_destination", None)
        if "date_of_birth" in applicant_data:
            applicant_data["date_of_birth"] = parse_date_of_birth(applicant_data["date_of_birth"])
        app_id = applicant_data.get("app_id")
        if not app_id:
            raise ValueError("Applicant data must contain an 'app_id'")

        # Ensure JSONB fields default to lists
        applicant_data.setdefault("activities", [])
        applicant_data.setdefault("awards", [])
        applicant_data.setdefault("ap_test_scores", [])
        applicant_data.setdefault("hooks", [])
        applicant_data.setdefault("documents", [])
        applicant_data.setdefault("status", "PENDING")

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                existing = None
                for candidate in applicant_id_candidates(app_id):
                    existing = session.execute(select(Applicant).where(Applicant.app_id == candidate)).scalar_one_or_none()
                    if existing:
                        break
                if existing:
                    updated_json_columns = set()
                    for k, v in applicant_data.items():
                        if update_fields is not None and k not in update_fields:
                            continue
                        if k == "documents" and not v and existing.documents:
                            continue
                        if k != "app_id" and hasattr(existing, k):
                            setattr(existing, k, v)
                            if k in ("activities", "awards", "ap_test_scores", "hooks", "documents"):
                                updated_json_columns.add(k)
                    for json_col in updated_json_columns:
                        flag_modified(existing, json_col)
                    existing.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(existing)
                    return existing
                else:
                    applicant_data["app_id"] = normalize_applicant_id(app_id) or app_id
                    new_app = Applicant(**applicant_data)
                    session.add(new_app)
                    session.commit()
                    session.refresh(new_app)
                    return new_app
            except Exception as e:
                session.rollback()
                logger.exception("Database stage_applicant failed for %s", app_id)
                raise
            finally:
                session.close()

        # Dry-run in-memory fallback
        existing_key = next((c for c in applicant_id_candidates(app_id) if c in self.dry_run_applicants), None)
        if existing_key is not None:
            cached = self.dry_run_applicants[existing_key]
            for k, v in applicant_data.items():
                if update_fields is not None and k not in update_fields:
                    continue
                if k == "documents" and not v and getattr(cached, "documents", None):
                    continue
                if k != "app_id" and hasattr(cached, k):
                    setattr(cached, k, v)
            return cached
        else:
            app_id = normalize_applicant_id(app_id) or app_id
            applicant_data["app_id"] = app_id
            cached = Applicant(**applicant_data)
            self.dry_run_applicants[app_id] = cached
            return cached

    def save_orphan(self, orphan_data: Dict[str, Any]) -> OrphanDocument:
        """Record an orphan document received without an existing CSV applicant row."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                existing = session.execute(
                    select(OrphanDocument).where(OrphanDocument.minio_key == orphan_data["minio_key"])
                ).scalar_one_or_none()
                if existing:
                    return existing
                orphan = OrphanDocument(**orphan_data)
                session.add(orphan)
                session.commit()
                session.refresh(orphan)
                return orphan
            except Exception as e:
                session.rollback()
                logger.exception("Database save_orphan failed for %s", orphan_data.get("minio_key"))
                raise
            finally:
                session.close()

        for orphan in self.dry_run_orphans:
            if orphan.minio_key == orphan_data["minio_key"]:
                return orphan
        orphan = OrphanDocument(**orphan_data)
        self.dry_run_orphans.append(orphan)
        return orphan

    def update_applicant_status(
        self,
        app_id: str,
        status: str,
        documents: Optional[List[Dict[str, Any]]] = None,
        *,
        audit_action: Optional[str] = None,
        audit_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update status and, when requested, append an audit row in one transaction."""
        if not app_id:
            return False

        candidates = applicant_id_candidates(app_id)

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                app = None
                for cand in candidates:
                    app = session.execute(select(Applicant).where(Applicant.app_id == cand)).scalar_one_or_none()
                    if app:
                        break
                if app:
                    previous_status = app.status
                    app.status = status
                    if documents is not None:
                        app.documents = documents
                        flag_modified(app, "documents")
                    app.updated_at = datetime.now(timezone.utc)
                    if audit_action:
                        session.add(AuditLog(
                            applicant_id=app.app_id,
                            action=audit_action,
                            details={
                                **(audit_details or {}),
                                "previous_status": previous_status,
                                "status": status,
                            },
                        ))
                    session.commit()
                    return True
            except Exception as e:
                session.rollback()
                logger.warning("Failed to update status in DB for %s: %s", app_id, e)
            finally:
                session.close()

        # A requested audit must never appear successful through the in-memory
        # fallback after a relational write fails.
        if audit_action and self.db_available:
            return False

        for cand in candidates:
            if cand in self.dry_run_applicants:
                cached = self.dry_run_applicants[cand]
                cached.status = status
                if documents is not None:
                    cached.documents = documents
                return True

        return False

    def get_applicant(self, app_id: str) -> Optional[Applicant]:
        """Retrieve an applicant record by ID with flexible format matching."""
        if not app_id:
            return None

        candidates = applicant_id_candidates(app_id)

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                for cand in candidates:
                    app = session.execute(select(Applicant).where(Applicant.app_id == cand)).scalar_one_or_none()
                    if app:
                        return app
                return None
            finally:
                session.close()

        for cand in candidates:
            if cand in self.dry_run_applicants:
                return self.dry_run_applicants[cand]
        return None

    def get_all_applicants(self) -> List[Applicant]:
        """Retrieve all staged applicant records."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                return list(session.execute(select(Applicant)).scalars().all())
            finally:
                session.close()
        return list(self.dry_run_applicants.values())

    def get_all_orphans(self) -> List[OrphanDocument]:
        """Retrieve all recorded orphan documents."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                return list(session.execute(select(OrphanDocument)).scalars().all())
            finally:
                session.close()
        return list(self.dry_run_orphans)

    def save_orphan_score(self, orphan_data: Dict[str, Any]) -> OrphanTestScore:
        """Record an orphan test score received without a matching applicant row."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                orphan = OrphanTestScore(**orphan_data)
                session.add(orphan)
                session.commit()
                session.refresh(orphan)
                return orphan
            except Exception as e:
                session.rollback()
                logger.exception("Database save_orphan_score failed for %s", orphan_data.get("identifier"))
                raise
            finally:
                session.close()

        # In-memory dry run
        data = dict(orphan_data)
        if "id" not in data or data["id"] is None:
            data["id"] = len(self.dry_run_orphan_scores) + 1
        orphan = OrphanTestScore(**data)
        self.dry_run_orphan_scores.append(orphan)
        return orphan

    def get_all_orphan_scores(self) -> List[OrphanTestScore]:
        """Retrieve all recorded orphan test scores."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                return list(session.execute(select(OrphanTestScore)).scalars().all())
            finally:
                session.close()
        return list(self.dry_run_orphan_scores)

    def find_applicant_by_email_or_dob(
        self,
        email: Optional[str] = None,
        dob: Optional[str] = None,
    ) -> Optional[Applicant]:
        """Match applicant by email (case-insensitive) or date_of_birth fallback."""
        clean_email = str(email).strip().lower() if email and str(email).strip() else None
        try:
            norm_dob = parse_date_of_birth(dob)
        except ValueError:
            norm_dob = None

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                if clean_email:
                    email_matches = session.execute(
                        select(Applicant).where(func.lower(Applicant.email_address) == clean_email)
                    ).scalars().all()
                    if len(email_matches) == 1:
                        return email_matches[0]
                    if len(email_matches) > 1:
                        logger.warning("Ambiguous score-feed email: %s", clean_email)
                        return None

                if norm_dob:
                    dob_matches = session.execute(
                        select(Applicant).where(Applicant.date_of_birth == norm_dob)
                    ).scalars().all()
                    if len(dob_matches) == 1:
                        return dob_matches[0]
                    if len(dob_matches) > 1:
                        logger.warning("Ambiguous score-feed date of birth: %s", norm_dob)
                return None
            finally:
                session.close()

        # Dry-run in-memory matching
        if clean_email:
            email_matches = [
                app for app in self.dry_run_applicants.values()
                if app.email_address and app.email_address.strip().lower() == clean_email
            ]
            if len(email_matches) == 1:
                return email_matches[0]
            if len(email_matches) > 1:
                logger.warning("Ambiguous score-feed email: %s", clean_email)
                return None

        if norm_dob:
            dob_matches = [
                app for app in self.dry_run_applicants.values()
                if app.date_of_birth and parse_date_of_birth(app.date_of_birth) == norm_dob
            ]
            if len(dob_matches) == 1:
                return dob_matches[0]
            if len(dob_matches) > 1:
                logger.warning("Ambiguous score-feed date of birth: %s", norm_dob)

        return None

    def update_applicant_scores(
        self,
        app_id: str,
        sat_math: Optional[int] = None,
        sat_ebrw: Optional[int] = None,
        act_composite: Optional[int] = None,
        ap_test_scores: Optional[List[Any]] = None,
        act_sections: Optional[Dict[str, Optional[int]]] = None,
        superscored_sat: Optional[float] = None,
        superscored_act: Optional[float] = None,
    ) -> Optional[Applicant]:
        """Update test score attributes for an applicant in DB or in-memory dry-run store."""
        if not app_id:
            return None

        candidates = applicant_id_candidates(app_id)

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                app = None
                for cand in candidates:
                    app = session.execute(select(Applicant).where(Applicant.app_id == cand)).scalar_one_or_none()
                    if app:
                        break
                if app:
                    if sat_math is not None:
                        app.sat_math = sat_math
                    if sat_ebrw is not None:
                        app.sat_ebrw = sat_ebrw
                    if superscored_sat is not None:
                        app.superscored_sat_score = max(app.superscored_sat_score or superscored_sat, superscored_sat)
                    elif sat_math is not None and sat_ebrw is not None:
                        total = float(sat_math + sat_ebrw)
                        app.superscored_sat_score = max(app.superscored_sat_score or total, total)

                    if act_composite is not None:
                        app.act_composite = act_composite
                        if superscored_act is not None:
                            app.superscored_act_score = max(app.superscored_act_score or superscored_act, superscored_act)
                        elif app.superscored_act_score is None or float(act_composite) > app.superscored_act_score:
                            app.superscored_act_score = float(act_composite)

                    if act_sections:
                        for sec_k, sec_v in act_sections.items():
                            if hasattr(app, sec_k) and sec_v is not None:
                                setattr(app, sec_k, sec_v)

                    if ap_test_scores is not None:
                        app.ap_test_scores = list(ap_test_scores)
                        flag_modified(app, "ap_test_scores")

                    app.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(app)
                    return app
            except Exception as e:
                session.rollback()
                logger.warning("Failed to update applicant scores for %s: %s", app_id, e)
            finally:
                session.close()

        for cand in candidates:
            if cand in self.dry_run_applicants:
                cached = self.dry_run_applicants[cand]
                if sat_math is not None:
                    cached.sat_math = sat_math
                if sat_ebrw is not None:
                    cached.sat_ebrw = sat_ebrw
                if superscored_sat is not None:
                    cached.superscored_sat_score = max(cached.superscored_sat_score or superscored_sat, superscored_sat)
                elif sat_math is not None and sat_ebrw is not None:
                    total = float(sat_math + sat_ebrw)
                    cached.superscored_sat_score = max(cached.superscored_sat_score or total, total)

                if act_composite is not None:
                    cached.act_composite = act_composite
                    if superscored_act is not None:
                        cached.superscored_act_score = max(cached.superscored_act_score or superscored_act, superscored_act)
                    elif cached.superscored_act_score is None or float(act_composite) > cached.superscored_act_score:
                        cached.superscored_act_score = float(act_composite)

                if act_sections:
                    for sec_k, sec_v in act_sections.items():
                        if hasattr(cached, sec_k) and sec_v is not None:
                            setattr(cached, sec_k, sec_v)

                if ap_test_scores is not None:
                    cached.ap_test_scores = list(ap_test_scores)

                cached.updated_at = datetime.now(timezone.utc)
                return cached

        return None

    def clear_local_store(self):
        """Reset/truncate local store for clean testing/dev states."""
        self.dry_run_applicants.clear()
        self.dry_run_orphans.clear()
        self.dry_run_orphan_scores.clear()
        if self.db_available and self.engine and 'sqlite' in str(self.engine.url):
            try:
                Base.metadata.drop_all(bind=self.engine)
                Base.metadata.create_all(bind=self.engine)
                logger.info('Cleared and recreated SQLite store tables.')
            except Exception as e:
                logger.warning('Error clearing SQLite store: %s', e)
