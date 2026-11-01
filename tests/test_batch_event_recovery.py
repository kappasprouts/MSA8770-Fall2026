"""Actual PostgreSQL + MinIO receipts in an isolated schema/bucket; simulated model."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import pymupdf
import pytest
import psycopg2
from sqlalchemy import create_engine,MetaData
from sqlalchemy.engine import URL

from storage.models import Base
from storage.storage_manager import StorageManager
from ingestion.pipeline import BatchIngestionPipeline
from ingestion import batch_events
from ai_agent import summarizing_agent as agent
from ai_agent import generation_recovery as recovery
from tests.test_generation_recovery import sample,StoppedProcess

pytestmark=pytest.mark.skipif(not (os.getenv('POSTGRES_DB') and os.getenv('TEST_MINIO_ENDPOINT')),reason='Requires PostgreSQL and isolated test MinIO configuration')
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def receiver(tmp_path,request,monkeypatch):
    schema='batch_recovery_test_'+uuid.uuid4().hex
    bucket='batch-recovery-'+uuid.uuid4().hex
    settings=dict(host=os.environ['POSTGRES_HOST'],port=os.environ['POSTGRES_PORT'],dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
    owner=psycopg2.connect(**settings);owner.autocommit=True
    from psycopg2 import sql
    with owner.cursor() as q:q.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    url=URL.create('postgresql+psycopg',username=settings['user'],password=settings['password'],host=settings['host'],port=int(settings['port']),database=settings['dbname'],query={'options':f'-c search_path={schema},public'})
    engine=create_engine(url)
    metadata=MetaData()
    for table in Base.metadata.tables.values():table.to_metadata(metadata,schema=schema)
    metadata.create_all(engine)
    store=StorageManager(database_url=url.render_as_string(hide_password=False),minio_endpoint=os.environ['TEST_MINIO_ENDPOINT'],
        minio_access_key=os.environ.get('TEST_MINIO_ACCESS_KEY','minioadmin'),minio_secret_key=os.environ.get('TEST_MINIO_SECRET_KEY','minioadmin'),
        minio_bucket=bucket,use_sqlite_fallback=False)
    assert store.db_available and not store.is_sqlite_fallback and store.minio_available
    def connect():return psycopg2.connect(**settings,options=f'-c search_path={schema},public')
    c=connect();agent.ensure_output_tables(c);recovery.ensure_schema(c)
    monkeypatch.setattr(agent,'RESULTS_DIR',tmp_path/'results')
    monkeypatch.setattr(agent,'retrieve_policies',lambda *_:[])
    calls=[];names={id(v):k for k,v in agent.SCHEMAS.items()}
    def model(prompt,schema,*_):
        assert 'PERSONAL ESSAY PRIVATE PHRASE' not in prompt
        calls.append(names[id(schema)])
        return json.dumps(sample(schema)),{'seconds':0,'output_tokens':5}
    monkeypatch.setattr(agent,'call_model',model)
    source=tmp_path/'batch';source.mkdir()
    (source/'applicant_data.csv').write_text('App_ID,First_Name,Last_Name,Date_Of_Birth,Email_Address,Unweighted_GPA\nAPP_101,Ada,West,2008-03-15,ada@example.test,3.80\nAPP_102,Ben,East,2008-04-16,ben@example.test,3.90\n')
    def pdf(path,message):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((40,50),message)
            data=doc.tobytes()
        path.write_bytes(data+b'\n% test padding '+b'x'*2200)
    for app in ('APP_101','APP_102'):
        folder=source/app;folder.mkdir()
        for filename in ('application_form.pdf','transcript.pdf','personal_statement.pdf','recommendation_letter_1.pdf','recommendation_letter_2.pdf'):
            pdf(folder/filename,'PERSONAL ESSAY PRIVATE PHRASE' if filename=='personal_statement.pdf' else 'Factual applicant document for controlled pipeline verification.')
    pdf(source/'APP_999_unknown.pdf','Unmatched synthetic file retained for intake.')
    def pipeline(path=source):return BatchIngestionPipeline(source_dir=path,config_path=ROOT/'policy/ingestion_rules.yaml',
        report_path=tmp_path/'artifacts/report.txt',affected_ids_path=tmp_path/'artifacts/ids.json',storage_manager=store,require_object_storage=True,require_postgresql=True)
    try:yield store,c,connect,pipeline,source,calls,model
    finally:
        if not c.closed:
            c.rollback();snapshot={}
            with c.cursor() as q:
                for table in ('applicants','audit_logs','orphan_documents','applicant_dossier','dossier_generation_runs','dossier_review_requests','dossier_publication_receipts','ingestion_batch_events','generation_batches','generation_batch_members','generation_executions'):
                    q.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t').format(sql.Identifier(table)));snapshot[table]=[r[0] for r in q.fetchall()]
            snapshot['minio_objects']=[]
            for obj in store.minio_client.list_objects(bucket,recursive=True):
                response=store.minio_client.get_object(bucket,obj.object_name)
                try:checksum=hashlib.sha256(response.read()).hexdigest()
                finally:response.close();response.release_conn()
                snapshot['minio_objects'].append({'bucket':bucket,'key':obj.object_name,'size':obj.size,'sha256':checksum})
            request.node.user_properties.append(('batch_receiver_snapshot',json.dumps(snapshot,default=str)))
            c.close()
        store.engine.dispose();engine.dispose()
        assert bucket.startswith('batch-recovery-') and schema.startswith('batch_recovery_test_')
        for obj in store.minio_client.list_objects(bucket,recursive=True):store.minio_client.remove_object(bucket,obj.object_name)
        store.minio_client.remove_bucket(bucket)
        with owner.cursor() as q:q.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        owner.close()

def test_same_batch_drop_twice_has_one_receiver_effect_and_one_dossier_each(receiver,monkeypatch,tmp_path):
    store,c,_,pipeline,source,calls,_=receiver
    uploads=[];original=store.upload_file
    def counted(*a,**k):uploads.append(k.get('minio_key'));return original(*a,**k)
    monkeypatch.setattr(store,'upload_file',counted)
    first=pipeline().run_batch();assert first['handoff_ready'] and first['batch_event_id'] and not first['deduplicated']
    assert batch_events.latest_summary(store)['batch_event_id']==first['batch_event_id']
    batch_id,results=recovery.run_batch(agent,c,store.minio_client,event_id=first['batch_event_id'])
    assert set(results.values())=={'DOSSIER_READY'}
    count=len(calls);put_count=len(uploads)
    copy=tmp_path/'redropped';shutil.copytree(source,copy)
    second=pipeline(copy).run_batch()
    assert second['batch_event_id']==first['batch_event_id'] and second['deduplicated']
    same,_=recovery.run_batch(agent,c,store.minio_client,event_id=second['batch_event_id'])
    assert same==batch_id and len(calls)==count and len(uploads)==put_count==11
    with c.cursor() as q:
        for table,expected in [('applicants',2),('orphan_documents',1),('audit_logs',2),('ingestion_batch_events',1),('generation_batches',1),('dossier_generation_runs',2),('applicant_dossier',2),('dossier_publication_receipts',2)]:
            q.execute(f'SELECT count(*) FROM {table}');assert q.fetchone()[0]==expected
    assert len(list(store.minio_client.list_objects(store.minio_bucket,recursive=True)))==11

def test_real_batch_interruption_after_one_dossier_resumes_second_from_sections(receiver,monkeypatch):
    store,c,connect,pipeline,_,calls,model=receiver
    event=pipeline().run_batch()['batch_event_id'];first=connect();stopped=[]
    def stop(prompt,schema,*args):
        if len(calls)==7 and not stopped:
            stopped.append(True);first.close();raise StoppedProcess()
        return model(prompt,schema,*args)
    monkeypatch.setattr(agent,'call_model',stop)
    with pytest.raises(StoppedProcess):recovery.run_batch(agent,first,store.minio_client,event_id=event)
    with c.cursor() as q:
        q.execute('SELECT id FROM generation_batches');batch=str(q.fetchone()[0])
        q.execute('SELECT count(*) FROM applicant_dossier');assert q.fetchone()[0]==1
    monkeypatch.setattr(agent,'call_model',model)
    _,results=recovery.run_batch(agent,c,store.minio_client,batch_id=batch)
    assert set(results.values())=={'DOSSIER_READY'}
    assert Counter(calls)=={'academic':2,'engagement':2,'recommendation':2,'policy':2,'synthesis':2}
    details=recovery.inspect_batch(c,batch,store.minio_client)
    assert details['batch']['state']=='COMPLETED'
    assert all(m['receipts']==1 and m['applicant_status']=='DOSSIER_READY' and m['final_run_id'] for m in details['members'])
    assert all(m['objects_verified'] is True and len(m['objects'])==5 for m in details['members'])

def test_completed_intake_missing_report_recovers_artifacts_without_reingestion(receiver,monkeypatch):
    store,c,_,pipeline,_,_,_=receiver
    from ingestion import run_ingestion_check as runner
    replace=runner.os.replace;failed=[]
    def interrupt(source,target):
        if str(target).endswith('.txt') and not failed:
            failed.append(True);raise OSError('controlled report publication failure')
        return replace(source,target)
    monkeypatch.setattr(runner.os,'replace',interrupt)
    with pytest.raises(OSError):pipeline().run_batch()
    with c.cursor() as q:
        q.execute('SELECT state,result IS NOT NULL FROM ingestion_batch_events');assert q.fetchone()==('FAILED',True)
    monkeypatch.setattr(runner.os,'replace',replace)
    monkeypatch.setattr(store,'upload_file',lambda *_a,**_k:pytest.fail('Must reuse saved receiver effects'))
    result=pipeline().run_batch();assert result['deduplicated'] and Path(result['handoff_file']).is_file()

@pytest.mark.parametrize('damage',['missing','changed'])
def test_missing_or_changed_receiving_object_does_not_replay_old_ingestion(receiver,damage):
    store,_,_,pipeline,_,_,_=receiver
    pipeline().run_batch()
    if damage=='missing':store.minio_client.remove_object(store.minio_bucket,'APP_101/transcript.pdf')
    else:
        import io
        store.minio_client.put_object(store.minio_bucket,'APP_101/transcript.pdf',io.BytesIO(b'changed'),7)
    with pytest.raises(Exception):pipeline().run_batch()

def test_changed_batch_creates_a_new_event(receiver):
    _,c,_,pipeline,source,_,_=receiver
    first=pipeline().run_batch()
    csv=source/'applicant_data.csv';csv.write_text(csv.read_text().replace('Ada','Ada Updated'))
    second=pipeline().run_batch()
    assert second['batch_event_id']!=first['batch_event_id'] and not second['deduplicated']

def test_intake_without_receiver_receipt_requires_explicit_repair_scope(receiver,monkeypatch):
    store,_,_,pipeline,_,_,_=receiver
    original=store.upload_file;calls=[]
    def stopped(*args,**kwargs):
        calls.append(True)
        if len(calls)==3:raise OSError('controlled failure before receipt')
        return original(*args,**kwargs)
    monkeypatch.setattr(store,'upload_file',stopped)
    with pytest.raises(OSError):pipeline().run_batch()
    monkeypatch.setattr(store,'upload_file',original)
    with pytest.raises(RuntimeError,match='explicit repair retry key'):pipeline().run_batch()
    repaired=pipeline().run_batch(retry_key='operator-confirmed-repair-1')
    assert repaired['handoff_ready'] and not repaired['deduplicated']

def test_unconfirmed_handoff_cannot_start_generation(receiver):
    store,c,_,pipeline,_,calls,_=receiver
    event=pipeline().run_batch()['batch_event_id']
    with c.cursor() as q:q.execute("UPDATE ingestion_batch_events SET manifest=jsonb_set(manifest,'{require_objects}','false') WHERE id=%s",(event,))
    c.commit()
    with pytest.raises(ValueError,match='did not confirm'):recovery.run_batch(agent,c,store.minio_client,event_id=event)
    assert not calls

def test_cross_process_batch_lock_prevents_overlapping_ingestion(receiver):
    from sqlalchemy import text
    store,_,_,pipeline,_,_,_=receiver
    with store.engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(hashtext(current_schema()),hashtext('batch-ingestion'))"));connection.commit()
        try:
            with pytest.raises(batch_events.BatchBusy):pipeline().run_batch()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtext(current_schema()),hashtext('batch-ingestion'))"));connection.commit()


def test_cli_style_runner_persists_handoff_without_api_summary_wrapper(receiver,tmp_path):
    from ingestion.run_ingestion_check import run_pipeline
    store,c,_,_,source,_,_=receiver
    result=run_pipeline(str(source),str(ROOT/'policy/ingestion_rules.yaml'),str(tmp_path/'cli_report.txt'),str(tmp_path/'cli_ids.json'),
        store,require_object_storage=True,require_postgresql=True)
    assert batch_events.latest_summary(store)['handoff_ready'] is True
    _,outcomes=recovery.run_batch(agent,c,store.minio_client,event_id=result.batch_event_id)
    assert set(outcomes.values())=={'DOSSIER_READY'}
