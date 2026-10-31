-- Apply after 20261030_officer_recommendation.sql.
-- Reflect existing human review progress without changing recommendations,
-- decision outcomes, or their timestamps. Safe to run more than once.
BEGIN;

UPDATE applicants
SET status = CASE
    WHEN final_decision IS NOT NULL THEN 'FINAL_DECISION_RECORDED'
    ELSE 'REVIEWED'
END
WHERE (final_decision IS NOT NULL OR officer_recommendation IS NOT NULL)
  AND status IS DISTINCT FROM CASE
      WHEN final_decision IS NOT NULL THEN 'FINAL_DECISION_RECORDED'
      ELSE 'REVIEWED'
  END;

COMMIT;
