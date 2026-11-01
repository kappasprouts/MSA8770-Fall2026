-- Requires the agent output tables (ensure_output_tables) and applicants.
-- Additive and idempotent. Legacy published dossiers retain a NULL request link.
BEGIN;

CREATE OR REPLACE FUNCTION checkpoint_applicant_snapshot(p_row jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
 SELECT (p_row - ARRAY['status','final_decision','officer_recommendation',
   'officer_recommendation_notes','officer_recommendation_updated_at','updated_at',
   'created_at','last_updated_csv','review_ctr','application_status_raw','create_date_time','documents'])
 || jsonb_build_object('documents', COALESCE((SELECT jsonb_agg(jsonb_build_object(
   'filename', d->'filename', 'type', COALESCE(d->'type',d->'doc_type'),
   'bucket',COALESCE(d->'minio_bucket',d->'bucket'), 'key',COALESCE(d->'object_key',d->'minio_key'),
   'sha256',COALESCE(d->'sha256',d->'sha256_checksum'), 'exists',d->'exists',
   'is_readable',d->'is_readable','error_message',d->'error_message')
   ORDER BY d->>'filename', COALESCE(d->>'minio_key',d->>'object_key'))
   FROM jsonb_array_elements(COALESCE(p_row->'documents','[]'::jsonb)) d),'[]'::jsonb));
$$;

CREATE OR REPLACE FUNCTION checkpoint_input_snapshot(p_app_id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE a jsonb; policies jsonb := '[]'::jsonb;
BEGIN
 SELECT checkpoint_applicant_snapshot(to_jsonb(x)) INTO a FROM applicants x WHERE app_id=p_app_id;
 IF a IS NULL THEN RAISE EXCEPTION 'Applicant not found'; END IF;
 IF to_regclass('policy_chunks') IS NOT NULL THEN
   EXECUTE 'SELECT COALESCE(jsonb_agg(to_jsonb(p)-''embedding''-''id'' ORDER BY policy_id, content),''[]''::jsonb) FROM policy_chunks p' INTO policies;
 END IF;
 RETURN jsonb_build_object('applicant',a,'policies',policies);
END $$;

CREATE TABLE IF NOT EXISTS dossier_review_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 app_id varchar(64) NOT NULL REFERENCES applicants(app_id),
 generation_run_id bigint NOT NULL REFERENCES dossier_generation_runs(id),
 action text NOT NULL DEFAULT 'PUBLISH_ADVISORY_DOSSIER' CHECK(action='PUBLISH_ADVISORY_DOSSIER'),
 candidate jsonb NOT NULL,
 candidate_hash text NOT NULL CHECK(candidate_hash=encode(sha256(convert_to(candidate::text,'UTF8')),'hex')),
 input_snapshot jsonb NOT NULL,
 input_hash text NOT NULL CHECK(input_hash=encode(sha256(convert_to(input_snapshot::text,'UTF8')),'hex')),
 pipeline_version text NOT NULL,
 state text NOT NULL DEFAULT 'REVIEW_PENDING' CHECK(state IN ('REVIEW_PENDING','PUBLISHED','REJECTED','ESCALATED','SUPERSEDED')),
 requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 expires_at timestamptz NOT NULL,
 requires_evidence_review boolean NOT NULL,
 review_owner text NOT NULL DEFAULT 'Admissions officer',
 escalation_owner text NOT NULL DEFAULT 'Senior admissions counselor',
 decision text CHECK(decision IN ('APPROVE','REJECT')),
 reviewer text,
 reason text,
 evidence_reviewed boolean,
 decided_at timestamptz,
 outcome_reason text,
 UNIQUE(app_id,input_hash,candidate_hash,pipeline_version)
);
CREATE UNIQUE INDEX IF NOT EXISTS dossier_one_pending_review ON dossier_review_requests(app_id) WHERE state='REVIEW_PENDING';
CREATE TABLE IF NOT EXISTS dossier_publication_receipts (
 request_id uuid PRIMARY KEY REFERENCES dossier_review_requests(id),
 app_id varchar(64) NOT NULL REFERENCES applicants(app_id),
 candidate_hash text NOT NULL,
 action text NOT NULL CHECK(action='PUBLISH_ADVISORY_DOSSIER'),
 published_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE applicant_dossier ADD COLUMN IF NOT EXISTS publication_request_id uuid REFERENCES dossier_review_requests(id);

CREATE OR REPLACE FUNCTION protect_dossier_review_content() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.app_id,NEW.generation_run_id,NEW.action,NEW.candidate,NEW.candidate_hash,
   NEW.input_snapshot,NEW.input_hash,NEW.pipeline_version,NEW.requested_at,NEW.expires_at,NEW.requires_evidence_review)
 IS DISTINCT FROM ROW(OLD.app_id,OLD.generation_run_id,OLD.action,OLD.candidate,OLD.candidate_hash,
   OLD.input_snapshot,OLD.input_hash,OLD.pipeline_version,OLD.requested_at,OLD.expires_at,OLD.requires_evidence_review)
 THEN RAISE EXCEPTION 'Review content and scope are immutable'; END IF;
 IF OLD.state<>'REVIEW_PENDING' AND NEW IS DISTINCT FROM OLD THEN
   RAISE EXCEPTION 'A completed review is immutable';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS dossier_review_content_immutable ON dossier_review_requests;
CREATE TRIGGER dossier_review_content_immutable BEFORE UPDATE ON dossier_review_requests
FOR EACH ROW EXECUTE FUNCTION protect_dossier_review_content();

CREATE OR REPLACE FUNCTION reconcile_dossier_reviews(p_app_id text DEFAULT NULL) RETURNS integer LANGUAGE plpgsql AS $$
DECLARE a record; r record; next_state text; n integer:=0;
BEGIN
 FOR a IN SELECT DISTINCT app_id FROM dossier_review_requests
   WHERE state='REVIEW_PENDING' AND (p_app_id IS NULL OR app_id=p_app_id) ORDER BY app_id LOOP
   PERFORM 1 FROM applicants WHERE app_id=a.app_id FOR UPDATE;
   FOR r IN SELECT * FROM dossier_review_requests WHERE app_id=a.app_id AND state='REVIEW_PENDING' FOR UPDATE LOOP
     next_state:=NULL;
     IF r.expires_at<=clock_timestamp() THEN next_state:='ESCALATED';
     ELSIF r.input_snapshot IS DISTINCT FROM checkpoint_input_snapshot(r.app_id) THEN next_state:='SUPERSEDED';
     END IF;
     IF next_state IS NOT NULL THEN
       UPDATE dossier_review_requests SET state=next_state, outcome_reason=CASE WHEN next_state='ESCALATED' THEN 'Review deadline expired; no publication authorized' ELSE 'Registered inputs or policies changed; new review required' END WHERE id=r.id;
       UPDATE applicants SET status=CASE WHEN final_decision IS NOT NULL THEN 'FINAL_DECISION_RECORDED'
         WHEN officer_recommendation IS NOT NULL THEN 'REVIEWED' ELSE 'REVIEW_'||next_state END WHERE app_id=r.app_id;
       INSERT INTO summary_audit_log(app_id,event,details) VALUES(r.app_id,'DOSSIER_REVIEW_'||next_state,jsonb_build_object('request_id',r.id));
       n:=n+1;
     END IF;
   END LOOP;
 END LOOP;
 RETURN n;
END $$;

CREATE OR REPLACE FUNCTION stage_dossier_review(p_app_id text,p_run_id bigint,p_candidate jsonb,p_input jsonb,p_pipeline text,p_expires timestamptz)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE a record; r dossier_review_requests; digest text; input_digest text; needs_review boolean;
BEGIN
 SELECT * INTO a FROM applicants WHERE app_id=p_app_id FOR UPDATE;
 IF to_regclass('policy_chunks') IS NOT NULL THEN EXECUTE 'LOCK TABLE policy_chunks IN SHARE MODE'; END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'Applicant not found'; END IF;
 IF a.final_decision IS NOT NULL OR a.officer_recommendation IS NOT NULL THEN
   RAISE EXCEPTION 'Reopening a human-reviewed application requires a separate authorized workflow';
 END IF;
 IF p_candidate->>'app_id' IS DISTINCT FROM p_app_id OR p_pipeline IS NULL OR length(p_pipeline)=0 THEN
   RAISE EXCEPTION 'Invalid candidate target or pipeline version'; END IF;
 IF NOT EXISTS(SELECT 1 FROM dossier_generation_runs WHERE id=p_run_id AND app_id=p_app_id
   AND run_status='REVIEW_PENDING' AND validation->'passed'='true'::jsonb) THEN
   RAISE EXCEPTION 'A successful validated generation run is required'; END IF;
 IF p_input IS DISTINCT FROM checkpoint_input_snapshot(p_app_id) THEN
   RAISE EXCEPTION 'Inputs changed during generation; candidate withheld'; END IF;
 IF p_expires<=clock_timestamp() OR p_expires>clock_timestamp()+interval '7 days' THEN
   RAISE EXCEPTION 'Review expiry must be in the future and within seven days'; END IF;
 digest:=encode(sha256(convert_to(p_candidate::text,'UTF8')),'hex');
 input_digest:=encode(sha256(convert_to(p_input::text,'UTF8')),'hex');
 PERFORM reconcile_dossier_reviews(p_app_id);
 SELECT * INTO r FROM dossier_review_requests WHERE app_id=p_app_id AND candidate_hash=digest AND input_hash=input_digest AND pipeline_version=p_pipeline;
 IF FOUND THEN
   UPDATE dossier_generation_runs SET run_status='REVIEW_REUSED' WHERE id=p_run_id AND id<>r.generation_run_id;
   UPDATE applicants SET status=CASE WHEN r.state='PUBLISHED' THEN 'DOSSIER_READY'
     WHEN r.state='REVIEW_PENDING' THEN 'REVIEW_PENDING' ELSE 'REVIEW_'||r.state END WHERE app_id=p_app_id;
   RETURN to_jsonb(r);
 END IF;
 FOR r IN SELECT * FROM dossier_review_requests WHERE app_id=p_app_id AND state='REVIEW_PENDING' FOR UPDATE LOOP
   UPDATE dossier_review_requests SET state='SUPERSEDED',outcome_reason='A newer candidate requires its own decision' WHERE id=r.id;
   INSERT INTO summary_audit_log(app_id,event,details) VALUES(p_app_id,'DOSSIER_REVIEW_SUPERSEDED',jsonb_build_object('request_id',r.id));
 END LOOP;
 SELECT COALESCE((validation->>'requires_human_verification')::boolean,false) INTO needs_review FROM dossier_generation_runs WHERE id=p_run_id;
 needs_review:=needs_review OR EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(p_candidate->'evidence_map','[]'::jsonb)) e WHERE e->>'verification_status'='UNVERIFIED_IMAGE_SOURCE');
 INSERT INTO dossier_review_requests(app_id,generation_run_id,candidate,candidate_hash,input_snapshot,input_hash,pipeline_version,expires_at,requires_evidence_review)
 VALUES(p_app_id,p_run_id,p_candidate,digest,p_input,input_digest,p_pipeline,p_expires,needs_review) RETURNING * INTO r;
 UPDATE applicants SET status='REVIEW_PENDING' WHERE app_id=p_app_id;
 INSERT INTO summary_audit_log(app_id,event,details) VALUES(p_app_id,'DOSSIER_REVIEW_REQUESTED',jsonb_build_object('request_id',r.id,'candidate_hash',r.candidate_hash,'expires_at',r.expires_at));
 RETURN to_jsonb(r);
END $$;

CREATE OR REPLACE FUNCTION decide_dossier_review(p_id uuid,p_hash text,p_action text,p_decision text,p_reviewer text,p_reason text,p_confirm boolean,p_evidence boolean)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE r dossier_review_requests; a record; receipt dossier_publication_receipts;
BEGIN
 IF p_decision IS NULL OR p_decision NOT IN ('APPROVE','REJECT') OR p_confirm IS DISTINCT FROM true
   OR p_action IS DISTINCT FROM 'PUBLISH_ADVISORY_DOSSIER' OR p_reviewer IS NULL OR length(trim(p_reviewer)) NOT BETWEEN 1 AND 200
   OR p_reason IS NULL OR length(trim(p_reason)) NOT BETWEEN 1 AND 10000 THEN
   RETURN jsonb_build_object('error','Explicit scoped decision, confirmation, reviewer and reason required','status',400); END IF;
 SELECT * INTO r FROM dossier_review_requests WHERE id=p_id;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','Review not found','status',404); END IF;
 SELECT * INTO a FROM applicants WHERE app_id=r.app_id FOR UPDATE;
 IF to_regclass('policy_chunks') IS NOT NULL THEN EXECUTE 'LOCK TABLE policy_chunks IN SHARE MODE'; END IF;
 SELECT * INTO r FROM dossier_review_requests WHERE id=p_id FOR UPDATE;
 IF p_hash IS DISTINCT FROM r.candidate_hash THEN RETURN jsonb_build_object('error','Candidate version mismatch','status',409); END IF;
 IF r.state IN ('PUBLISHED','REJECTED') THEN
   IF r.decision=p_decision AND r.reviewer=trim(p_reviewer) AND r.reason=trim(p_reason)
     AND r.evidence_reviewed IS NOT DISTINCT FROM COALESCE(p_evidence,false) THEN
     SELECT * INTO receipt FROM dossier_publication_receipts WHERE request_id=r.id;
     RETURN jsonb_build_object('request',to_jsonb(r),'receipt',CASE WHEN receipt.request_id IS NULL THEN NULL ELSE to_jsonb(receipt) END,'replayed',true,'status',200);
   END IF;
   RETURN jsonb_build_object('error','Conflicting decision; recorded outcome is immutable','status',409);
 END IF;
 PERFORM reconcile_dossier_reviews(r.app_id);
 SELECT * INTO r FROM dossier_review_requests WHERE id=p_id;
 IF r.state<>'REVIEW_PENDING' THEN RETURN jsonb_build_object('error','Review is expired or superseded; publication withheld','request',to_jsonb(r),'status',409); END IF;
 IF a.final_decision IS NOT NULL OR a.officer_recommendation IS NOT NULL THEN
   RETURN jsonb_build_object('error','Application already has a human disposition; publication withheld','status',409); END IF;
 IF p_decision='APPROVE' AND r.requires_evidence_review AND p_evidence IS DISTINCT FROM true THEN
   RETURN jsonb_build_object('error','Verify the flagged source evidence before approving','status',400); END IF;
 IF p_decision='APPROVE' THEN
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
   INSERT INTO dossier_publication_receipts(request_id,app_id,candidate_hash,action) VALUES(r.id,r.app_id,r.candidate_hash,r.action) RETURNING * INTO receipt;
   UPDATE dossier_generation_runs SET run_status='DOSSIER_READY' WHERE id=r.generation_run_id;
   UPDATE applicants SET status='DOSSIER_READY' WHERE app_id=r.app_id;
 ELSE
   UPDATE applicants SET status='REVIEW_REJECTED' WHERE app_id=r.app_id;
 END IF;
 UPDATE dossier_review_requests SET state=CASE WHEN p_decision='APPROVE' THEN 'PUBLISHED' ELSE 'REJECTED' END,
   decision=p_decision,reviewer=trim(p_reviewer),reason=trim(p_reason),evidence_reviewed=COALESCE(p_evidence,false),decided_at=clock_timestamp()
   WHERE id=r.id RETURNING * INTO r;
 INSERT INTO summary_audit_log(app_id,event,details) VALUES(r.app_id,'DOSSIER_REVIEW_'||r.state,
   jsonb_build_object('request_id',r.id,'candidate_hash',r.candidate_hash,'reviewer',r.reviewer,'reason',r.reason,'authentication','SIMULATED_FOR_PROTOTYPE'));
 RETURN jsonb_build_object('request',to_jsonb(r),'receipt',CASE WHEN receipt.request_id IS NULL THEN NULL ELSE to_jsonb(receipt) END,'replayed',false,'status',200);
END $$;
COMMIT;
