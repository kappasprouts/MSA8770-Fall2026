-- Requires applicants, audit_logs and the existing dossier checkpoint functions.
BEGIN;
CREATE TABLE IF NOT EXISTS it_exception_cases (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 exception_key text NOT NULL,
 fingerprint text NOT NULL CHECK(length(fingerprint)=64),
 applicant_id text,
 source text NOT NULL CHECK(source IN ('INGESTION','SUMMARIZER','ORPHAN_INTAKE')),
 snapshot jsonb NOT NULL,
 state text NOT NULL DEFAULT 'OPEN' CHECK(state IN ('OPEN','IN_PROGRESS','WAITING','RESOLVED','SUPERSEDED')),
 owner text,
 revision integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 resolution_evidence jsonb,
 UNIQUE(exception_key,fingerprint)
);
CREATE TABLE IF NOT EXISTS it_exception_actions (
 command_id uuid PRIMARY KEY,
 case_id uuid NOT NULL REFERENCES it_exception_cases(id),
 action text NOT NULL CHECK(action IN ('CLAIM','NOTE','HANDOFF','REQUEST_RETRY','VERIFY_RESOLVED')),
 actor text NOT NULL,
 note text NOT NULL,
 request jsonb NOT NULL,
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS it_retry_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 case_id uuid NOT NULL REFERENCES it_exception_cases(id),
 command_id uuid UNIQUE NOT NULL REFERENCES it_exception_actions(command_id) DEFERRABLE INITIALLY DEFERRED,
 applicant_id text NOT NULL,
 source text NOT NULL CHECK(source IN ('INGESTION','SUMMARIZER')),
 source_version text NOT NULL,
 failure_run_id bigint,
 state text NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','STALE','NEEDS_RECHECK')),
 worker_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 finished_at timestamptz,
 result jsonb
);
CREATE UNIQUE INDEX IF NOT EXISTS it_one_active_retry_per_applicant ON it_retry_jobs(applicant_id)
 WHERE state IN ('QUEUED','RUNNING','NEEDS_RECHECK');
CREATE TABLE IF NOT EXISTS it_retry_workers (
 id uuid PRIMARY KEY,
 last_seen timestamptz NOT NULL DEFAULT now(),
 ingestion_enabled boolean NOT NULL DEFAULT false
);
COMMIT;
