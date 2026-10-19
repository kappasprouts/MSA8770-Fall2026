-- Run once against an existing PostgreSQL database before deploying the
-- status-only Applicant model. New databases are created from storage/models.py.
BEGIN;

-- The accompanying Applicant model edit introduced ib_test_scores. Preserve
-- previously ingested IB_Courses values when upgrading an older database.
ALTER TABLE applicants
    ADD COLUMN IF NOT EXISTS ib_test_scores JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'applicants'
          AND column_name = 'ib_courses'
    ) THEN
        EXECUTE $sql$
            UPDATE applicants
            SET ib_test_scores = to_jsonb(regexp_split_to_array(btrim(ib_courses), '[[:space:]]*,[[:space:]]*'))
            WHERE ib_courses IS NOT NULL
              AND btrim(ib_courses) <> ''
              AND ib_test_scores = '[]'::jsonb
        $sql$;
    END IF;
END $$;

ALTER TABLE applicants DROP COLUMN IF EXISTS routing_destination;

COMMIT;
