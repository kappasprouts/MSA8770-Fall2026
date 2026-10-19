-- Run once if audit_logs was created from the earlier documentation, which
-- named the timestamp column "timestamp". The active ORM uses created_at.
BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'audit_logs'
          AND column_name = 'timestamp'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'audit_logs'
          AND column_name = 'created_at'
    ) THEN
        ALTER TABLE audit_logs RENAME COLUMN "timestamp" TO created_at;
    END IF;
END $$;

COMMIT;
