-- Convert the existing applicants.date_of_birth column to PostgreSQL DATE.
-- This is transactional: an unrecognized or invalid stored date aborts the
-- migration rather than silently changing or discarding an applicant's DOB.
BEGIN;

DO $$
DECLARE
    current_type text;
BEGIN
    SELECT data_type INTO current_type
    FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'applicants'
      AND column_name = 'date_of_birth';

    IF current_type IN ('character varying', 'text') THEN
        ALTER TABLE applicants
            ALTER COLUMN date_of_birth TYPE DATE
            USING CASE
                WHEN date_of_birth IS NULL OR btrim(date_of_birth) = '' THEN NULL
                WHEN btrim(date_of_birth) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                    THEN btrim(date_of_birth)::date
                WHEN btrim(date_of_birth) ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                    THEN make_date(
                        substr(btrim(date_of_birth), 1, 4)::integer,
                        substr(btrim(date_of_birth), 6, 2)::integer,
                        substr(btrim(date_of_birth), 9, 2)::integer
                    )
                WHEN btrim(date_of_birth) ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
                    THEN make_date(
                        substr(btrim(date_of_birth), 7, 4)::integer,
                        substr(btrim(date_of_birth), 1, 2)::integer,
                        substr(btrim(date_of_birth), 4, 2)::integer
                    )
                WHEN btrim(date_of_birth) ~ '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
                     AND substr(btrim(date_of_birth), 1, 2)::integer <= 12
                    THEN make_date(
                        substr(btrim(date_of_birth), 7, 4)::integer,
                        substr(btrim(date_of_birth), 1, 2)::integer,
                        substr(btrim(date_of_birth), 4, 2)::integer
                    )
                WHEN btrim(date_of_birth) ~ '^[0-9]{2}-[0-9]{2}-[0-9]{4}$'
                    THEN make_date(
                        substr(btrim(date_of_birth), 7, 4)::integer,
                        substr(btrim(date_of_birth), 4, 2)::integer,
                        substr(btrim(date_of_birth), 1, 2)::integer
                    )
                ELSE btrim(date_of_birth)::date
            END;
    ELSIF current_type IS DISTINCT FROM 'date' THEN
        RAISE EXCEPTION 'Unexpected applicants.date_of_birth type: %', current_type;
    END IF;
END $$;

COMMIT;
