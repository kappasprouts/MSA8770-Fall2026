"""Storage and MinIO connection manager for Riverview Admissions Pipeline.

Provides robust PostgreSQL and MinIO connection handlers, reading configuration
from environment variables (.env / os.environ). If PostgreSQL or MinIO connections
are unavailable, logs clear warnings and permits dry-run local manifest generation,
while performing real uploads and inserts when services are online.
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.parse

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker, Session

try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_SDK_AVAILABLE = True
except ImportError:
    MINIO_SDK_AVAILABLE = False

from storage.database import Base
from storage.models import (
    Applicant,
    AuditLog,
    DocumentRecord,
    OrphanDocument,
    OrphanTestScore,
)

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages relational (PostgreSQL) and object storage (MinIO) interactions
    with automatic dry-run fallback when services are not reachable.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        minio_endpoint: Optional[str] = None,
        minio_access_key: Optional[str] = None,
        minio_secret_key: Optional[str] = None,
        minio_secure: Optional[bool] = None,
        minio_bucket: Optional[str] = None,
    ):
        # Database Configuration
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/riverview_admissions",
        )
        # Adapt postgresql:// to postgresql+psycopg:// if using psycopg v3
        if self.database_url.startswith("postgresql://") and not self.database_url.startswith("postgresql+"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

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

    def _init_db_connection(self):
        """Attempt to establish PostgreSQL connection, falling back gracefully to dry-run."""
        # Fast probe for host/port reachability before engine creation
        if not self.database_url.startswith("sqlite"):
            try:
                parsed = urllib.parse.urlsplit(self.database_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 5432
                if not self._is_reachable(host, port, timeout=0.2):
                    self.db_available = False
                    logger.warning(
                        "Database host %s:%s is not reachable. Operating in dry-run local mode.",
                        host,
                        port,
                    )
                    return
            except Exception:
                pass

        try:
            if self.database_url.startswith("sqlite"):
                self.engine = create_engine(self.database_url, connect_args={"check_same_thread": False})
            else:
                self.engine = create_engine(self.database_url, pool_pre_ping=True)

            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            Base.metadata.create_all(bind=self.engine)
            self.db_available = True
            logger.info("Successfully connected to database at: %s", self._safe_url(self.database_url))
        except Exception as e:
            self.db_available = False
            self.engine = None
            self.SessionLocal = None
            logger.warning(
                "Could not connect to database (%s). Operating in dry-run local mode for relational storage.",
                str(e),
            )

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
            logger.warning("MinIO upload failed for %s (%s). Falling back to recorded key.", minio_key, e)
            return minio_key

    def stage_applicant(self, applicant_data: Dict[str, Any]) -> Applicant:
        """Stage or upsert an applicant record into PostgreSQL or dry-run store."""
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
        applicant_data.setdefault("routing_destination", "READY_FOR_REVIEW")

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                existing = session.execute(select(Applicant).where(Applicant.app_id == app_id)).scalar_one_or_none()
                if existing:
                    for k, v in applicant_data.items():
                        if hasattr(existing, k):
                            setattr(existing, k, v)
                    existing.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(existing)
                    return existing
                else:
                    new_app = Applicant(**applicant_data)
                    session.add(new_app)
                    session.commit()
                    session.refresh(new_app)
                    return new_app
            except Exception as e:
                session.rollback()
                logger.warning("Database stage_applicant failed for %s (%s). Using dry-run cache.", app_id, e)
            finally:
                session.close()

        # Dry-run in-memory fallback
        if app_id in self.dry_run_applicants:
            cached = self.dry_run_applicants[app_id]
            for k, v in applicant_data.items():
                if hasattr(cached, k):
                    setattr(cached, k, v)
            return cached
        else:
            cached = Applicant(**applicant_data)
            self.dry_run_applicants[app_id] = cached
            return cached

    def save_orphan(self, orphan_data: Dict[str, Any]) -> OrphanDocument:
        """Record an orphan document received without an existing CSV applicant row."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                orphan = OrphanDocument(**orphan_data)
                session.add(orphan)
                session.commit()
                session.refresh(orphan)
                return orphan
            except Exception as e:
                session.rollback()
                logger.warning("Database save_orphan failed (%s). Using dry-run cache.", e)
            finally:
                session.close()

        orphan = OrphanDocument(**orphan_data)
        self.dry_run_orphans.append(orphan)
        return orphan

    def update_applicant_status(
        self,
        app_id: str,
        status: str,
        routing_destination: str,
        documents: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Update the gate evaluation status and documents of an applicant."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                app = session.execute(select(Applicant).where(Applicant.app_id == app_id)).scalar_one_or_none()
                if app:
                    app.status = status
                    app.routing_destination = routing_destination
                    if documents is not None:
                        app.documents = documents
                    app.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    return True
            except Exception as e:
                session.rollback()
                logger.warning("Failed to update status in DB for %s: %s", app_id, e)
            finally:
                session.close()

        if app_id in self.dry_run_applicants:
            cached = self.dry_run_applicants[app_id]
            cached.status = status
            cached.routing_destination = routing_destination
            if documents is not None:
                cached.documents = documents
            return True

        return False

    def get_applicant(self, app_id: str) -> Optional[Applicant]:
        """Retrieve an applicant record by ID."""
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                return session.execute(select(Applicant).where(Applicant.app_id == app_id)).scalar_one_or_none()
            finally:
                session.close()
        return self.dry_run_applicants.get(app_id)

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
                logger.warning("Database save_orphan_score failed (%s). Using dry-run cache.", e)
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
        clean_email = email.strip().lower() if email and str(email).strip() else None
        clean_dob = dob.strip() if dob and str(dob).strip() else None

        def _norm_dob(dob_str: Optional[str]) -> Optional[str]:
            if not dob_str:
                return None
            s = str(dob_str).strip()
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            return s

        norm_dob = _norm_dob(clean_dob) if clean_dob else None

        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                if clean_email:
                    app = session.execute(
                        select(Applicant).where(func.lower(Applicant.email_address) == clean_email)
                    ).scalar_one_or_none()
                    if app:
                        return app

                if clean_dob:
                    app = session.execute(
                        select(Applicant).where(Applicant.date_of_birth == clean_dob)
                    ).scalars().first()
                    if app:
                        return app

                    if norm_dob:
                        all_apps = session.execute(
                            select(Applicant).where(Applicant.date_of_birth.is_not(None))
                        ).scalars().all()
                        for a in all_apps:
                            if _norm_dob(a.date_of_birth) == norm_dob:
                                return a
                return None
            finally:
                session.close()

        # Dry-run in-memory matching
        if clean_email:
            for app in self.dry_run_applicants.values():
                if app.email_address and app.email_address.strip().lower() == clean_email:
                    return app

        if clean_dob:
            for app in self.dry_run_applicants.values():
                if app.date_of_birth and (
                    app.date_of_birth.strip() == clean_dob
                    or (norm_dob and _norm_dob(app.date_of_birth) == norm_dob)
                ):
                    return app

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
        if self.db_available and self.SessionLocal:
            session: Session = self.SessionLocal()
            try:
                app = session.execute(select(Applicant).where(Applicant.app_id == app_id)).scalar_one_or_none()
                if app:
                    if sat_math is not None:
                        app.sat_math = sat_math
                    if sat_ebrw is not None:
                        app.sat_ebrw = sat_ebrw
                    if superscored_sat is not None:
                        app.superscored_sat_score = superscored_sat
                    elif sat_math is not None and sat_ebrw is not None:
                        app.superscored_sat_score = float(sat_math + sat_ebrw)

                    if act_composite is not None:
                        app.act_composite = act_composite
                        if superscored_act is not None:
                            app.superscored_act_score = superscored_act
                        elif app.superscored_act_score is None or float(act_composite) > app.superscored_act_score:
                            app.superscored_act_score = float(act_composite)

                    if act_sections:
                        for sec_k, sec_v in act_sections.items():
                            if hasattr(app, sec_k) and sec_v is not None:
                                setattr(app, sec_k, sec_v)

                    if ap_test_scores is not None:
                        app.ap_test_scores = list(ap_test_scores)

                    app.updated_at = datetime.now(timezone.utc)
                    session.commit()
                    session.refresh(app)
                    return app
            except Exception as e:
                session.rollback()
                logger.warning("Failed to update applicant scores for %s: %s", app_id, e)
            finally:
                session.close()

        if app_id in self.dry_run_applicants:
            cached = self.dry_run_applicants[app_id]
            if sat_math is not None:
                cached.sat_math = sat_math
            if sat_ebrw is not None:
                cached.sat_ebrw = sat_ebrw
            if superscored_sat is not None:
                cached.superscored_sat_score = superscored_sat
            elif sat_math is not None and sat_ebrw is not None:
                cached.superscored_sat_score = float(sat_math + sat_ebrw)

            if act_composite is not None:
                cached.act_composite = act_composite
                if superscored_act is not None:
                    cached.superscored_act_score = superscored_act
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
