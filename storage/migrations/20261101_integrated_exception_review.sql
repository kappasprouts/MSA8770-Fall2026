-- Apply after 20261031_durable_dossier_review.sql. No existing decisions are changed.
BEGIN;
ALTER TABLE dossier_review_requests ADD COLUMN IF NOT EXISTS review_mode text NOT NULL DEFAULT 'LEGACY_MANUAL'
 CHECK(review_mode IN ('LEGACY_MANUAL','EXCEPTION','AUTOMATIC'));
ALTER TABLE dossier_review_requests ADD COLUMN IF NOT EXISTS exception_reasons jsonb NOT NULL DEFAULT '[]';

CREATE OR REPLACE FUNCTION dossier_exception_reasons(candidate jsonb, validation jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
 SELECT COALESCE(jsonb_agg(reason),'[]'::jsonb) FROM (
   SELECT 'Source evidence needs human verification' AS reason
   WHERE validation->'requires_human_verification'='true'::jsonb OR EXISTS (
     SELECT 1 FROM jsonb_array_elements(COALESCE(candidate->'evidence_map','[]')) e
     WHERE COALESCE(e->>'verification_status','NOT_VERIFIED') <> 'TEXT_VERIFIED')
   UNION ALL SELECT 'The dossier contains source conflicts, missing information or reading notes'
   WHERE jsonb_array_length(COALESCE(candidate->'review_notes','[]'))>0
   UNION ALL SELECT 'A policy assessment has insufficient evidence'
   WHERE EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(candidate->'policy_assessment','[]')) p WHERE p->>'alignment'='unclear')
 ) reasons;
$$;

-- Classification is fixed once a newly staged request has been routed.
CREATE OR REPLACE FUNCTION protect_dossier_review_classification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.review_mode,NEW.exception_reasons) IS DISTINCT FROM ROW(OLD.review_mode,OLD.exception_reasons)
   AND (OLD.state<>'REVIEW_PENDING' OR OLD.review_mode<>'LEGACY_MANUAL') THEN
   RAISE EXCEPTION 'Review classification is immutable';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS dossier_review_classification_immutable ON dossier_review_requests;
CREATE TRIGGER dossier_review_classification_immutable BEFORE UPDATE ON dossier_review_requests
FOR EACH ROW EXECUTE FUNCTION protect_dossier_review_classification();

CREATE OR REPLACE FUNCTION route_dossier_candidate(p_app_id text,p_run_id bigint,p_candidate jsonb,p_input jsonb,p_pipeline text,p_expires timestamptz)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r dossier_review_requests; staged jsonb; reasons jsonb;
BEGIN
 -- Staging locks the applicant/policy version and requires a fully validated run.
 staged:=stage_dossier_review(p_app_id,p_run_id,p_candidate,p_input,p_pipeline,p_expires);
 SELECT * INTO r FROM dossier_review_requests WHERE id=(staged->>'id')::uuid FOR UPDATE;
 -- A retry recovers the saved outcome; it never reopens a closed authorization.
 IF r.state<>'REVIEW_PENDING' OR r.review_mode<>'LEGACY_MANUAL' THEN RETURN to_jsonb(r); END IF;
 SELECT dossier_exception_reasons(r.candidate,validation) INTO reasons FROM dossier_generation_runs WHERE id=r.generation_run_id;
 UPDATE dossier_review_requests SET review_mode=CASE WHEN jsonb_array_length(reasons)>0 THEN 'EXCEPTION' ELSE 'AUTOMATIC' END,
   exception_reasons=reasons WHERE id=r.id RETURNING * INTO r;
 IF r.review_mode='EXCEPTION' THEN RETURN to_jsonb(r); END IF;

 -- Automatic availability is a system action, never recorded as human approval.
 INSERT INTO applicant_dossier(app_id,applicant_demographics,academic_profile,engagement_profile,recommendation_profile,
   supplemental_essay_profile,strengths,review_notes,policy_assessment,holistic_assessment,evidence_map,generated_at,updated_at,publication_request_id)
 VALUES(r.app_id,r.candidate->'applicant_demographics',r.candidate->'academic_profile',r.candidate->'engagement_profile',
   r.candidate->'recommendation_profile',r.candidate->'supplemental_essay_profile',r.candidate->'strengths',r.candidate->'review_notes',
   r.candidate->'policy_assessment',r.candidate->>'holistic_assessment',r.candidate->'evidence_map',r.requested_at,clock_timestamp(),r.id)
 ON CONFLICT(app_id) DO UPDATE SET applicant_demographics=EXCLUDED.applicant_demographics,academic_profile=EXCLUDED.academic_profile,
   engagement_profile=EXCLUDED.engagement_profile,recommendation_profile=EXCLUDED.recommendation_profile,
   supplemental_essay_profile=EXCLUDED.supplemental_essay_profile,strengths=EXCLUDED.strengths,review_notes=EXCLUDED.review_notes,
   policy_assessment=EXCLUDED.policy_assessment,holistic_assessment=EXCLUDED.holistic_assessment,evidence_map=EXCLUDED.evidence_map,
   generated_at=EXCLUDED.generated_at,updated_at=EXCLUDED.updated_at,publication_request_id=EXCLUDED.publication_request_id;
 INSERT INTO dossier_publication_receipts(request_id,app_id,candidate_hash,action) VALUES(r.id,r.app_id,r.candidate_hash,r.action);
 UPDATE dossier_generation_runs SET run_status='DOSSIER_READY' WHERE id=r.generation_run_id;
 UPDATE applicants SET status='DOSSIER_READY' WHERE app_id=r.app_id;
 UPDATE dossier_review_requests SET state='PUBLISHED',outcome_reason='Automated checks passed; no identified exceptions. Human admissions review remains required.'
   WHERE id=r.id RETURNING * INTO r;
 INSERT INTO summary_audit_log(app_id,event,details) VALUES(r.app_id,'DOSSIER_AUTOMATICALLY_AVAILABLE',
   jsonb_build_object('request_id',r.id,'candidate_hash',r.candidate_hash,'actor','SYSTEM','human_approval',false));
 RETURN to_jsonb(r);
END $$;
COMMIT;
