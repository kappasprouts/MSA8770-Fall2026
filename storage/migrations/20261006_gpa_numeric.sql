-- Convert GPA columns in an existing PostgreSQL applicants table to
-- NUMERIC(5,3). Values are rounded to three decimal places. The transaction
-- aborts if an existing value cannot fit the new range (-99.999 to 99.999).
BEGIN;

ALTER TABLE applicants
    ALTER COLUMN unweighted_gpa TYPE NUMERIC(5,3)
    USING round(unweighted_gpa::numeric, 3),
    ALTER COLUMN weighted_gpa TYPE NUMERIC(5,3)
    USING round(weighted_gpa::numeric, 3);

COMMIT;
