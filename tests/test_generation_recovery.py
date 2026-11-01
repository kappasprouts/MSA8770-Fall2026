"""Durable generation across actual PostgreSQL connections; controlled responses."""
from collections import Counter
import json
import os
import uuid

import pytest
from psycopg2.extras import Json

from tests.test_durable_review import checkpoint_db
from ai_agent import summarizing_agent as agent
from ai_agent import generation_recovery as recovery

pytestmark=pytest.mark.skipif(not os.getenv('POSTGRES_DB'),reason='Requires configured PostgreSQL')
class StoppedProcess(BaseException): pass

def sample(schema):
    kind=schema['type']
    if isinstance(kind,list):return None
    if kind=='object':return {key:sample(value) for key,value in schema['properties'].items()}
    if kind=='array':return []
    if kind=='string':return schema.get('enum',['Factual advisory summary.'])[0]
    return 0

@pytest.fixture
def controlled(checkpoint_db,monkeypatch,tmp_path,request):
    c,connect=checkpoint_db;recovery.ensure_schema(c)
    monkeypatch.setattr(agent,'RESULTS_DIR',tmp_path)
    monkeypatch.setattr(agent,'retrieve_policies',lambda *_:[])
    monkeypatch.setattr(agent,'load_pages',lambda *_:([{'document_type':'transcript','filename':'transcript.pdf','page_number':1,'text':'Factual source','png_bytes':b'image'}],[]))
    calls=[]
    names={id(schema):name for name,schema in agent.SCHEMAS.items()}
    def model(prompt,schema,*_):
        calls.append(names[id(schema)])
        return json.dumps(sample(schema)),{'seconds':0,'output_tokens':5}
    monkeypatch.setattr(agent,'call_model',model)
    yield c,connect,calls,model
    c.rollback()
    snapshot={}
    with c.cursor() as q:
        for table in ('generation_executions','generation_section_checkpoints','generation_batches','generation_batch_members'):
            q.execute(f'SELECT to_jsonb(t) FROM {table} t');snapshot[table]=[r[0] for r in q.fetchall()]
    request.node.user_properties.append(('generation_receiver_snapshot',json.dumps(snapshot,default=str)))

def test_closed_connection_resumes_only_unfinished_sections(controlled,monkeypatch):
    c,connect,calls,model=controlled
    first=connect();stopped=[];rag_calls=[]
    monkeypatch.setattr(agent,'retrieve_policies',lambda *_:rag_calls.append(True) or [])
    def interrupted(prompt,schema,*args):
        if schema is agent.SCHEMAS['recommendation'] and not stopped:
            stopped.append(True);calls.append('recommendation_inflight');first.close();raise StoppedProcess()
        return model(prompt,schema,*args)
    monkeypatch.setattr(agent,'call_model',interrupted)
    with pytest.raises(StoppedProcess):agent.process_applicant(first,None,'APP_050')
    with c.cursor() as q:
        q.execute('SELECT state FROM generation_executions');assert q.fetchone()[0]=='RUNNING'
        q.execute('SELECT section FROM generation_section_checkpoints ORDER BY section');assert q.fetchall()==[('academic',),('engagement',)]
    second=connect()
    try:assert agent.process_applicant(second,None,'APP_050')=='DOSSIER_READY'
    finally:second.close()
    assert Counter(calls)=={'academic':1,'engagement':1,'recommendation_inflight':1,'recommendation':1,'policy':1,'synthesis':1}
    assert len(rag_calls)==1
    with c.cursor() as q:
        q.execute('SELECT state,resume_count FROM generation_executions');assert q.fetchone()==('COMPLETED',1)
        for table in ('applicant_dossier','dossier_publication_receipts','dossier_generation_runs'):
            q.execute(f'SELECT count(*) FROM {table}');assert q.fetchone()[0]==1

def test_completed_receipt_lost_before_export_does_not_repeat_publication(controlled,monkeypatch):
    c,_,calls,_=controlled
    original=agent.write_result_file
    monkeypatch.setattr(agent,'write_result_file',lambda *_:(_ for _ in ()).throw(OSError('controlled export failure')))
    with pytest.raises(OSError):agent.process_applicant(c,None,'APP_050')
    monkeypatch.setattr(agent,'write_result_file',original)
    assert agent.process_applicant(c,None,'APP_050')=='DOSSIER_READY'
    assert len(calls)==5
    with c.cursor() as q:
        q.execute('SELECT count(*) FROM dossier_publication_receipts');assert q.fetchone()[0]==1

def test_failed_attempts_keep_the_same_retry_budget_on_resume(controlled,monkeypatch):
    c,_,calls,model=controlled
    def invalid(prompt,schema,*args):
        if schema is agent.SCHEMAS['academic']:
            calls.append('invalid_academic');return '{}',{'seconds':0,'output_tokens':1}
        return model(prompt,schema,*args)
    monkeypatch.setattr(agent,'call_model',invalid)
    original=agent.save_run
    monkeypatch.setattr(agent,'save_run',lambda *_a,**_k:(_ for _ in ()).throw(StoppedProcess()))
    with pytest.raises(StoppedProcess):agent.process_applicant(c,None,'APP_050')
    count=len(calls)
    monkeypatch.setattr(agent,'save_run',original)
    assert agent.process_applicant(c,None,'APP_050')=='AI_VALIDATION_FAILED'
    assert len(calls)==count and calls.count('invalid_academic')==2
    assert agent.process_applicant(c,None,'APP_050')=='AI_VALIDATION_FAILED'
    assert len(calls)==count
    with c.cursor() as q:
        q.execute('SELECT state FROM generation_executions');assert q.fetchone()[0]=='FAILED'
        q.execute('SELECT count(*) FROM applicant_dossier');assert q.fetchone()[0]==0

@pytest.mark.parametrize('change',["UPDATE applicants SET superscored_sat_score=1599","INSERT INTO policy_chunks VALUES('POL-NEW','Changed policy')"])
def test_changed_inputs_or_policy_cannot_reuse_old_sections(controlled,monkeypatch,change):
    c,connect,calls,model=controlled;other=connect()
    changed=[]
    def drift(prompt,schema,*args):
        result=model(prompt,schema,*args)
        if not changed:
            with other.cursor() as q:q.execute(change)
            other.commit();changed.append(True)
        return result
    monkeypatch.setattr(agent,'call_model',drift)
    try:
        with pytest.raises(recovery.StaleGeneration):agent.process_applicant(c,None,'APP_050')
    finally:other.close()
    with c.cursor() as q:
        q.execute('SELECT state FROM generation_executions');assert q.fetchone()[0]=='SUPERSEDED'
        q.execute('SELECT count(*) FROM applicant_dossier');assert q.fetchone()[0]==0
    monkeypatch.setattr(agent,'call_model',model)
    assert agent.process_applicant(c,None,'APP_050')=='DOSSIER_READY'
    assert calls.count('academic')==2

def test_per_applicant_lock_and_owner_token_fence_old_workers(controlled):
    c,connect,_,_=controlled;second=connect()
    try:
        with recovery.exclusive(c,'generation:APP_050'):
            with pytest.raises(recovery.GenerationBusy):agent.process_applicant(second,None,'APP_050')
        snapshot=agent.review_checkpoint.capture_input_snapshot(c,agent.get_applicant(c,'APP_050'))
        execution=recovery.Execution(c,'APP_050',snapshot,agent.generation_pipeline_version(),'fence-test')
        with second.cursor() as q:q.execute('UPDATE generation_executions SET owner_token=%s WHERE id=%s',(str(uuid.uuid4()),execution.id))
        second.commit()
        with pytest.raises(recovery.StaleGeneration):execution.save_attempt('academic','hash',{},[],[])
    finally:second.close()

@pytest.mark.parametrize('drift',[False,True])
def test_interrupted_multi_applicant_batch_resumes_without_repeating_done_member(controlled,monkeypatch,drift):
    c,connect,calls,model=controlled
    with c.cursor() as q:q.execute("INSERT INTO applicants(app_id,status) VALUES('APP_051','READY_FOR_REVIEW')")
    c.commit();first=connect();stopped=[]
    def interrupted(prompt,schema,*args):
        # The first applicant consumes five calls. Stop during applicant two.
        if len(calls)==7 and not stopped:
            stopped.append(True);first.close();raise StoppedProcess()
        return model(prompt,schema,*args)
    monkeypatch.setattr(agent,'call_model',interrupted)
    with pytest.raises(StoppedProcess):recovery.run_batch(agent,first,None,['APP_050','APP_051'])
    with c.cursor() as q:
        q.execute('SELECT id FROM generation_batches');batch_id=str(q.fetchone()[0])
        q.execute('SELECT app_id,state FROM generation_batch_members ORDER BY app_id');assert q.fetchall()==[('APP_050','DONE'),('APP_051','RUNNING')]
        if drift:q.execute("UPDATE applicants SET superscored_sat_score=1599 WHERE app_id='APP_051'")
    c.commit()
    if not drift:
        pending=recovery.inspect_batch(c,batch_id)
        second=next(m for m in pending['members'] if m['app_id']=='APP_051')
        assert set(second['section_checkpoints'])=={'academic','engagement'}
    monkeypatch.setattr(agent,'call_model',model)
    _,results=recovery.run_batch(agent,c,None,batch_id=batch_id)
    assert results['APP_050']=='DOSSIER_READY'
    assert results['APP_051']==('INPUTS_CHANGED' if drift else 'DOSSIER_READY')
    assert calls.count('academic')==2 and calls.count('engagement')==2
    with c.cursor() as q:
        q.execute('SELECT state FROM generation_batches');assert q.fetchone()[0]==('NEEDS_ATTENTION' if drift else 'COMPLETED')
        q.execute('SELECT count(*) FROM dossier_publication_receipts');assert q.fetchone()[0]==(1 if drift else 2)
    count=len(calls)
    recovery.run_batch(agent,c,None,batch_id=batch_id)
    assert len(calls)==count

def test_batch_scope_is_rechecked_after_the_applicant_lock(controlled):
    c,_,calls,_=controlled
    expected=recovery.input_hash(c,'APP_050')
    with c.cursor() as q:q.execute('UPDATE applicants SET superscored_sat_score=1599')
    c.commit()
    with pytest.raises(recovery.StaleGeneration):agent.process_applicant(c,None,'APP_050',expected_input_hash=expected)
    assert not calls


def test_force_or_recovery_cannot_override_a_missing_materials_gate(controlled):
    c,_,calls,_=controlled
    with c.cursor() as q:q.execute("UPDATE applicants SET status='AWAITING_MATERIALS'")
    c.commit()
    assert agent.process_applicant(c,None,'APP_050',force=True)=='SKIPPED'
    assert not calls


def test_two_decimal_gpa_scope_hash_matches_batch_and_execution(controlled):
    c,_,calls,_=controlled
    with c.cursor() as q:
        q.execute('ALTER TABLE applicants ADD COLUMN unweighted_gpa numeric(3,2)')
        q.execute('UPDATE applicants SET unweighted_gpa=3.80')
    c.commit()
    batch,_=recovery.run_batch(agent,c,None,['APP_050'])
    detail=recovery.inspect_batch(c,batch)['members'][0]
    assert detail['execution_id'] and detail['execution_state']=='COMPLETED'
    assert detail['section_checkpoints']['academic']['passed'] is True
    with c.cursor() as q:
        q.execute('SELECT e.input_hash=m.input_hash FROM generation_executions e JOIN generation_batch_members m ON m.execution_id=e.id')
        assert q.fetchone()[0] is True
    recovery.run_batch(agent,c,None,batch_id=batch)
    assert len(calls)==5
