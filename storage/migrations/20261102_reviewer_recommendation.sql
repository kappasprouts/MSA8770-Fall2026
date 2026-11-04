-- Run once against an existing PostgreSQL database before deploying the
-- Applicant Review recommendation panel. New databases are created from storage/models.py.
BEGIN;

-- Advisory recommendation recorded by the application reviewer. It is shown to
-- the Dean on the Final Decisions screen and never replaces final_decision.
ALTER TABLE applicants
    ADD COLUMN IF NOT EXISTS reviewer_recommendation VARCHAR(10),
    ADD COLUMN IF NOT EXISTS reviewer_recommendation_note TEXT,
    ADD COLUMN IF NOT EXISTS reviewer_recommended_at TIMESTAMPTZ;

COMMIT;
