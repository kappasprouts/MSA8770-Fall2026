BEGIN;
CREATE TABLE IF NOT EXISTS ingestion_batch_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_hash text UNIQUE NOT NULL,
 manifest jsonb NOT NULL, state text NOT NULL DEFAULT 'STARTED'
 CHECK(state IN ('STARTED','INGESTED','COMPLETED','INTERRUPTED','FAILED')),
 result jsonb, report_text text, effects jsonb, delivery_summary jsonb, last_error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS generation_executions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), app_id text NOT NULL REFERENCES applicants(app_id),
 input_snapshot jsonb NOT NULL, input_hash text NOT NULL, pipeline_version text NOT NULL, retry_key text NOT NULL,
 state text NOT NULL DEFAULT 'RUNNING' CHECK(state IN ('RUNNING','INTERRUPTED','COMPLETED','FAILED','SUPERSEDED')),
 owner_token uuid NOT NULL, context jsonb NOT NULL DEFAULT '{}', outcome text, final_run_id bigint, review_request_id uuid,
 resume_count integer NOT NULL DEFAULT 0, last_error text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(app_id,input_hash,pipeline_version,retry_key)
);
CREATE TABLE IF NOT EXISTS generation_section_checkpoints (
 execution_id uuid NOT NULL REFERENCES generation_executions(id), section text NOT NULL,
 request_hash text NOT NULL, output jsonb, errors jsonb NOT NULL, attempts jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(execution_id,section)
);
CREATE TABLE IF NOT EXISTS generation_batches (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), identity_hash text UNIQUE NOT NULL,
 ingestion_event_id uuid REFERENCES ingestion_batch_events(id), pipeline_version text NOT NULL,
 retry_key text NOT NULL, state text NOT NULL DEFAULT 'RUNNING'
 CHECK(state IN ('RUNNING','INTERRUPTED','COMPLETED','NEEDS_ATTENTION')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS generation_batch_members (
 batch_id uuid NOT NULL REFERENCES generation_batches(id), app_id text NOT NULL,
 input_hash text, state text NOT NULL DEFAULT 'PENDING'
 CHECK(state IN ('PENDING','RUNNING','DONE','FAILED','STALE','SKIPPED')),
 outcome text, execution_id uuid REFERENCES generation_executions(id), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(batch_id,app_id)
);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_class WHERE relname='dossier_generation_runs' AND relnamespace=current_schema()::regnamespace) THEN
   ALTER TABLE dossier_generation_runs ADD COLUMN IF NOT EXISTS execution_id uuid REFERENCES generation_executions(id);
   CREATE UNIQUE INDEX IF NOT EXISTS dossier_run_one_execution ON dossier_generation_runs(execution_id);
 END IF;
END $$;
COMMIT;
