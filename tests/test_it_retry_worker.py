"""Actual PostgreSQL retry-job effects; model responses are controlled."""
import json
import os
import uuid

import pytest
from psycopg2.extras import Json

from tests.test_durable_review import checkpoint_db, candidate
from ingestion import it_retry_worker as worker
from ai_agent import summarizing_agent as agent

pytestmark=pytest.mark.skipif(not os.getenv("POSTGRES_DB"),reason="Requires test PostgreSQL")


@pytest.fixture
def it_db(checkpoint_db,request):
    c,connect=checkpoint_db
    worker.ensure_schema(c);worker.ensure_schema(c)
    with c.cursor() as q:
        q.execute("CREATE TABLE audit_logs(id text PRIMARY KEY,applicant_id text,action text,actor text,details jsonb,created_at timestamptz DEFAULT now())")
        q.execute("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES('APP_050','AI_VALIDATION_FAILED','{\"passed\":false}') RETURNING id")
        run_id=q.fetchone()[0]
        q.execute("UPDATE applicants SET status='AI_VALIDATION_FAILED'")
        q.execute("SELECT encode(sha256(convert_to(checkpoint_input_snapshot('APP_050')::text,'UTF8')),'hex')")
        source=q.fetchone()[0]
        case_id=str(uuid.uuid4());command_id=str(uuid.uuid4())
        q.execute("INSERT INTO it_exception_cases(id,exception_key,fingerprint,applicant_id,source,snapshot,state) VALUES(%s,'applicant-APP_050-summarizer',%s,'APP_050','SUMMARIZER','{}','WAITING')",(case_id,'a'*64))
        q.execute("INSERT INTO it_exception_actions(command_id,case_id,action,actor,note,request,result) VALUES(%s,%s,'REQUEST_RETRY','IT demo','Corrected service; retry this version','{}','{}')",(command_id,case_id))
        q.execute("INSERT INTO it_retry_jobs(case_id,command_id,applicant_id,source,source_version,failure_run_id) VALUES(%s,%s,'APP_050','SUMMARIZER',%s,%s)",(case_id,command_id,source,run_id))
    c.commit()
    yield c,connect
    c.rollback()
    evidence={}
    with c.cursor() as q:
        for table in ('it_exception_cases','it_retry_jobs','it_exception_actions'):
            q.execute(f"SELECT to_jsonb(x) FROM {table} x")
            evidence[table]=[row[0] for row in q.fetchall()]
    request.node.user_properties.append(('it_receiver_snapshot',json.dumps(evidence,default=str)))


def claim(c):
    actor=str(uuid.uuid4());worker.heartbeat(c,actor,False)
    return worker.claim_job(c,actor)


def test_worker_claims_once_across_connections(it_db):
    c,connect=it_db
    job=claim(c);assert job
    second=connect()
    try:
        assert worker.claim_job(second,str(uuid.uuid4())) is None
        with second.cursor() as q:
            q.execute("SELECT pg_try_advisory_lock(hashtext('it-retry:APP_050'))")
            assert not q.fetchone()[0]
    finally: second.close()
    worker.execute_job(c,job,summarizer=lambda *_: (_ for _ in ()).throw(RuntimeError('controlled failure')))


@pytest.mark.parametrize('change',["UPDATE applicants SET superscored_sat_score=1599","UPDATE applicants SET officer_recommendation='WAITLIST'"])
def test_changed_input_or_human_disposition_withholds_retry(it_db,change):
    c,_=it_db;job=claim(c)
    with c.cursor() as q:q.execute(change)
    c.commit()
    worker.execute_job(c,job,summarizer=lambda *_:pytest.fail('Must not invoke model'))
    with c.cursor() as q:
        q.execute('SELECT state FROM it_retry_jobs');assert q.fetchone()[0]=='STALE'
        q.execute('SELECT count(*) FROM applicant_dossier');assert q.fetchone()[0]==0


def sample(schema):
    kind=schema['type']
    if isinstance(kind,list):return None
    if kind=='object':return {key:sample(value) for key,value in schema['properties'].items()}
    if kind=='array':return []
    if kind=='string':return schema.get('enum',['Factual summary.'])[0]
    return 0


@pytest.mark.parametrize('flagged',[False,True])
def test_retry_executes_actual_generator_and_verifies_receiver(it_db,monkeypatch,tmp_path,flagged):
    c,_=it_db;job=claim(c)
    monkeypatch.setattr(agent,'RESULTS_DIR',tmp_path)
    def model(prompt,schema,*_):
        output=sample(schema)
        if flagged and 'document_facts' in output:output['notes']=[{'category':'unclear','note':'Source requires officer verification.'}]
        return json.dumps(output),{'seconds':0,'output_tokens':5}
    monkeypatch.setattr(agent,'call_model',model)
    monkeypatch.setattr(agent,'retrieve_policies',lambda *_:[])
    monkeypatch.setattr(agent,'load_pages',lambda *_:([{'document_type':'transcript','filename':'transcript.pdf','page_number':1,'text':'Factual source','png_bytes':b'image'}],[]))
    worker.execute_job(c,job,summarizer=lambda conn,j:agent.process_applicant(conn,None,j['applicant_id'],force=True))
    with c.cursor() as q:
        q.execute('SELECT state,result FROM it_retry_jobs');state,result=q.fetchone()
        assert state=='SUCCEEDED' and result['verified'] is True
        assert result['review_state']==('REVIEW_PENDING' if flagged else 'PUBLISHED')
        q.execute('SELECT state FROM it_exception_cases');assert q.fetchone()[0]=='RESOLVED'
        q.execute('SELECT officer_recommendation,final_decision FROM applicants');assert q.fetchone()==(None,None)
        q.execute('SELECT count(*) FROM dossier_publication_receipts');assert q.fetchone()[0]==(0 if flagged else 1)


def test_failed_retry_does_not_close_case(it_db):
    c,_=it_db;job=claim(c)
    worker.execute_job(c,job,summarizer=lambda *_: (_ for _ in ()).throw(RuntimeError('controlled load failure')))
    with c.cursor() as q:
        q.execute('SELECT state,result FROM it_retry_jobs');state,result=q.fetchone()
        assert state=='FAILED' and not result['verified']
        q.execute('SELECT state FROM it_exception_cases');assert q.fetchone()[0]=='IN_PROGRESS'


def test_worker_crash_requires_receiver_recheck_not_blind_requeue(it_db):
    c,connect=it_db;job=claim(c)
    with c.cursor() as q:q.execute("UPDATE it_retry_workers SET last_seen=now()-interval '2 minutes'")
    c.commit()
    second=connect()
    try:
        worker.recover_interrupted(second)
        with second.cursor() as q:
            q.execute('SELECT state FROM it_retry_jobs');assert q.fetchone()[0]=='NEEDS_RECHECK'
        assert worker.claim_job(second,str(uuid.uuid4())) is None
    finally:second.close()
    # Simulate the original worker reconnecting with a truthful failed outcome.
    worker.execute_job(c,job,summarizer=lambda *_: (_ for _ in ()).throw(RuntimeError()))


def test_ingestion_retry_requires_explicit_source_directory(it_db,monkeypatch):
    c,_=it_db;monkeypatch.delenv('INGESTION_INPUT_DIR',raising=False)
    with pytest.raises(RuntimeError,match='explicit INGESTION_INPUT_DIR'):
        worker.run_ingestion(c,{'applicant_id':'APP_050'})


def test_packet_retry_adapter_checks_canonical_gate_receipt(it_db,monkeypatch,tmp_path):
    from ingestion import pipeline
    from storage import storage_manager
    c,_=it_db
    monkeypatch.setenv('INGESTION_INPUT_DIR',str(tmp_path))
    with c.cursor() as q:
        q.execute("UPDATE applicants SET status='ERROR'")
        q.execute("UPDATE it_retry_jobs SET source='INGESTION'")
        q.execute("UPDATE it_exception_cases SET source='INGESTION'")
    c.commit()
    actor=str(uuid.uuid4());worker.heartbeat(c,actor,True);job=worker.claim_job(c,actor,True)
    calls=[]
    previous_url=os.getenv('DATABASE_URL')
    sentinel=object()
    monkeypatch.setattr(storage_manager,'StorageManager',lambda **_:sentinel)
    class ControlledGate:
        def __init__(self,storage_manager):assert storage_manager is sentinel
        def process_packet(self,app_id,retry_key=None):
            calls.append(app_id)
            with c.cursor() as q:
                q.execute("UPDATE applicants SET status='READY_FOR_REVIEW' WHERE app_id=%s",(app_id,))
                q.execute("INSERT INTO audit_logs(id,applicant_id,action,actor,details) VALUES(%s,%s,'MANIFEST_EVALUATED','system_pipeline','{\"processing_status\":\"READY_FOR_REVIEW\"}')",(str(uuid.uuid4()),app_id))
            c.commit()
            return {'status':'READY_FOR_REVIEW','hard_stop':True,'storage_mode':'postgresql','object_storage_required':True,'handoff_ready':True}
    monkeypatch.setattr(pipeline,'BatchIngestionPipeline',ControlledGate)
    worker.execute_job(c,job)
    assert os.getenv('DATABASE_URL')==previous_url
    assert calls==['APP_050']
    with c.cursor() as q:
        q.execute('SELECT state,result FROM it_retry_jobs');state,result=q.fetchone()
        assert state=='SUCCEEDED' and result['verified'] and result['receiver']['manifest_audit_id']
        q.execute('SELECT count(*) FROM applicant_dossier');assert q.fetchone()[0]==0


def test_completed_retry_update_and_audit_are_atomic(it_db):
    c,_=it_db;job=claim(c)
    with c.cursor() as q:q.execute("ALTER TABLE audit_logs ADD CONSTRAINT fail_it_finish CHECK(false) NOT VALID")
    c.commit()
    with pytest.raises(Exception):worker.finish_job(c,job,'SUCCEEDED',{'verified':True})
    c.rollback()
    with c.cursor() as q:
        q.execute('SELECT state FROM it_retry_jobs');assert q.fetchone()[0]=='RUNNING'
        q.execute('SELECT state FROM it_exception_cases');assert q.fetchone()[0]=='WAITING'


def test_lost_result_save_recovers_publication_without_repeating(it_db,monkeypatch):
    c,_=it_db;job=claim(c)
    def publish(conn,j):
        with conn.cursor() as q:
            q.execute("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES('APP_050','REVIEW_PENDING','{\"passed\":true}') RETURNING id")
            run_id=q.fetchone()[0]
            q.execute("SELECT route_dossier_candidate('APP_050',%s,%s,checkpoint_input_snapshot('APP_050'),'v1',now()+interval '1 day')",(run_id,Json(candidate())))
        conn.commit()
    original=worker.finish_job;calls=[]
    def interrupted(*args):
        calls.append(True)
        if len(calls)==1:raise RuntimeError('controlled lost confirmation')
        return original(*args)
    monkeypatch.setattr(worker,'finish_job',interrupted)
    worker.execute_job(c,job,summarizer=publish)
    with c.cursor() as q:
        q.execute('SELECT state FROM it_retry_jobs');assert q.fetchone()[0]=='SUCCEEDED'
        q.execute('SELECT count(*) FROM dossier_publication_receipts');assert q.fetchone()[0]==1
