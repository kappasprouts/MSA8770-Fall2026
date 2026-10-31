-- Apply to existing PostgreSQL databases before starting the updated review UI.
-- New databases receive these columns from storage/models.py.
BEGIN;

ALTER TABLE applicants
    ADD COLUMN IF NOT EXISTS officer_recommendation VARCHAR(10),
    ADD COLUMN IF NOT EXISTS officer_recommendation_notes TEXT,
    ADD COLUMN IF NOT EXISTS officer_recommendation_updated_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'applicants'::regclass
          AND conname = 'ck_applicants_officer_recommendation'
    ) THEN
        ALTER TABLE applicants ADD CONSTRAINT ck_applicants_officer_recommendation
            CHECK (officer_recommendation IN ('ACCEPT', 'REJECT', 'WAITLIST'));
    END IF;
END $$;

COMMIT;
