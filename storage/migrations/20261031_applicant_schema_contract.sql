-- Current contract. Apply after older migrations; safe to repeat.
-- Missing year/term are stored as NULL. GPA uses decimal half-up rounding
-- to two places. Values outside NUMERIC(3,2)'s range abort the transaction.
BEGIN;

ALTER TABLE applicants
    ALTER COLUMN admission_year DROP NOT NULL,
    ALTER COLUMN admission_term DROP NOT NULL,
    ALTER COLUMN unweighted_gpa TYPE NUMERIC(3,2)
        USING round(unweighted_gpa::numeric, 2),
    ALTER COLUMN weighted_gpa TYPE NUMERIC(3,2)
        USING round(weighted_gpa::numeric, 2);

COMMIT;
