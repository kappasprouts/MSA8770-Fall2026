"""PostgreSQL-owned generation scope, per-attempt checkpoints and batch progress."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

from psycopg2.extras import Json, RealDictCursor
try:
    from .review_checkpoint import json_default
except ImportError:
    from review_checkpoint import json_default

MIGRATION=Path(__file__).resolve().parents[1]/'storage/migrations/20261101_durable_batch_generation.sql'
GOOD={'DOSSIER_READY','REVIEW_PENDING'}

class GenerationBusy(RuntimeError): pass
class StaleGeneration(RuntimeError): pass

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=json_default,separators=(',',':')).encode()).hexdigest()

def ensure_schema(connection):
    with connection.cursor() as q:
        q.execute("SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='generation_executions' AND relnamespace=current_schema()::regnamespace)")
        present=q.fetchone()[0]
        q.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='dossier_generation_runs' AND column_name='execution_id')")
        linked=q.fetchone()[0]
    connection.commit()
    if not present or not linked:
        with connection.cursor() as q:q.execute(MIGRATION.read_text(encoding='utf-8'))

@contextmanager
def exclusive(connection,key):
    with connection.cursor() as q:
        q.execute("SELECT pg_try_advisory_lock(hashtext(current_schema()),hashtext(%s))",(key,))
        acquired=q.fetchone()[0]
    connection.commit()
    if not acquired:raise GenerationBusy(f'Work is already running for {key}; retry after the current owner finishes')
    try:yield
    finally:
        if not connection.closed:
            connection.rollback()
            with connection.cursor() as q:q.execute("SELECT pg_advisory_unlock(hashtext(current_schema()),hashtext(%s))",(key,))
            connection.commit()

def input_hash(connection,app_id):
    with connection.cursor() as q:
        q.execute("SELECT encode(sha256(convert_to(checkpoint_input_snapshot(%s)::text,'UTF8')),'hex')",(app_id,))
        return q.fetchone()[0]

class Execution:
    def __init__(self,connection,app_id,snapshot,version,retry_key):
        self.connection=connection;self.token=str(uuid.uuid4())
        with connection.cursor(cursor_factory=RealDictCursor) as q:
            # Hash/store the server snapshot itself. JSON's float roundtrip can
            # change numeric text (3.80 -> 3.8) while jsonb equality stays true.
            q.execute("""INSERT INTO generation_executions(app_id,input_snapshot,input_hash,pipeline_version,retry_key,owner_token)
              SELECT %s,snapshot,encode(sha256(convert_to(snapshot::text,'UTF8')),'hex'),%s,%s,%s
              FROM (SELECT checkpoint_input_snapshot(%s) AS snapshot) source WHERE snapshot=%s::jsonb
              ON CONFLICT(app_id,input_hash,pipeline_version,retry_key) DO NOTHING""",(app_id,version,retry_key,self.token,app_id,Json(snapshot)))
            q.execute("SELECT * FROM generation_executions WHERE app_id=%s AND input_snapshot=%s AND pipeline_version=%s AND retry_key=%s FOR UPDATE",(app_id,Json(snapshot),version,retry_key))
            selected=q.fetchone()
            if not selected:raise StaleGeneration('Inputs changed while creating execution scope')
            self.row=dict(selected)
            if self.row['state'] in {'RUNNING','INTERRUPTED'}:
                resumed=str(self.row['owner_token'])!=self.token
                q.execute("UPDATE generation_executions SET state='RUNNING',owner_token=%s,resume_count=resume_count+%s,updated_at=now() WHERE id=%s",(self.token,int(resumed),self.row['id']))
        connection.commit()
        self.id=str(self.row['id']);self.app_id=app_id;self.snapshot=snapshot

    @property
    def terminal(self):return self.row['state'] in {'COMPLETED','FAILED','SUPERSEDED'}

    def assert_current(self):
        with self.connection.cursor() as q:
            q.execute("SELECT owner_token::text,state,input_snapshot=checkpoint_input_snapshot(app_id) FROM generation_executions WHERE id=%s",(self.id,))
            token,state,fresh=q.fetchone()
        self.connection.commit()
        if token!=self.token or state!='RUNNING':raise StaleGeneration('Execution ownership changed; old worker is fenced out')
        if not fresh:raise StaleGeneration('Applicant inputs or policies changed; saved sections cannot authorize this version')

    def policies(self,loader):
        self.assert_current()
        if 'policies' in self.row['context']:return deepcopy(self.row['context']['policies'])
        policies=loader()
        self.assert_current()
        self.row['context']['policies']=policies
        with self.connection.cursor() as q:
            q.execute("UPDATE generation_executions SET context=%s,updated_at=now() WHERE id=%s AND owner_token=%s",(Json(self.row['context']),self.id,self.token))
        self.connection.commit()
        return policies

    def attempt(self,section,request_hash):
        self.assert_current()
        with self.connection.cursor(cursor_factory=RealDictCursor) as q:
            q.execute("SELECT * FROM generation_section_checkpoints WHERE execution_id=%s AND section=%s",(self.id,section))
            row=q.fetchone()
        self.connection.commit()
        if row and row['request_hash']!=request_hash:raise StaleGeneration(f'{section} prompt/source context changed; cached output withheld')
        return dict(row) if row else None

    def save_attempt(self,section,request_hash,output,errors,attempts):
        self.assert_current()
        with self.connection.cursor() as q:
            q.execute("""INSERT INTO generation_section_checkpoints(execution_id,section,request_hash,output,errors,attempts)
              VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(execution_id,section) DO UPDATE SET
              request_hash=EXCLUDED.request_hash,output=EXCLUDED.output,errors=EXCLUDED.errors,attempts=EXCLUDED.attempts,updated_at=now()""",
              (self.id,section,request_hash,Json(output),Json(errors),Json(attempts)))
        self.connection.commit()

    def finish_in_transaction(self,outcome,run_id=None,review_id=None):
        with self.connection.cursor() as q:
            q.execute("""UPDATE generation_executions SET state=%s,outcome=%s,final_run_id=%s,review_request_id=%s,updated_at=now()
              WHERE id=%s AND owner_token=%s AND state='RUNNING'""",('COMPLETED' if outcome in GOOD else 'FAILED',outcome,run_id,review_id,self.id,self.token))
            if q.rowcount!=1:raise StaleGeneration('Execution no longer owns publication')

    def interrupted(self,error):
        if self.connection.closed:return
        self.connection.rollback()
        with self.connection.cursor() as q:
            q.execute("UPDATE generation_executions SET state=%s,last_error=%s,updated_at=now() WHERE id=%s AND owner_token=%s AND state='RUNNING'",
                ('SUPERSEDED' if isinstance(error,StaleGeneration) else 'INTERRUPTED',type(error).__name__,self.id,self.token))
        self.connection.commit()

def run_applicant(agent,connection,minio_client,app_id,force=False,generation_key=None,expected_input_hash=None):
    # Pure unit tests supply None; every real PostgreSQL invocation uses durable scope.
    if connection is None:return agent._process_applicant(connection,minio_client,app_id,force)
    applicant=agent.get_applicant(connection,app_id)
    if not applicant or applicant.get('officer_recommendation') or applicant.get('final_decision') or agent.current_test_scores(applicant)[1] or applicant.get('status') in {'INCOMPLETE','AWAITING_MATERIALS','REPLACEMENT_REQUESTED','COUNSELOR_REVIEW'}:
        return agent._process_applicant(connection,minio_client,app_id,force)
    ensure_schema(connection)
    with exclusive(connection,'generation:'+app_id):
        applicant=agent.get_applicant(connection,app_id)
        if applicant.get('officer_recommendation') or applicant.get('final_decision'):return 'SKIPPED'
        snapshot=agent.review_checkpoint.capture_input_snapshot(connection,applicant)
        if expected_input_hash and input_hash(connection,app_id)!=expected_input_hash:
            connection.commit()
            raise StaleGeneration('Batch/retry input version changed before execution ownership was acquired')
        version=agent.generation_pipeline_version()
        if not force:
            cached=agent.review_checkpoint.existing_review(connection,app_id,snapshot,version)
            if cached:return cached
        retry_key=generation_key or ('force-'+str(uuid.uuid4()) if force else 'normal')
        # A saved execution may resume after an infrastructure error changed status.
        with connection.cursor() as q:
            q.execute("SELECT 1 FROM generation_executions WHERE app_id=%s AND input_snapshot=%s AND pipeline_version=%s AND retry_key=%s",(app_id,Json(snapshot),version,retry_key))
            exists=q.fetchone()
        connection.commit()
        if applicant.get('status')!='READY_FOR_REVIEW' and not force and not exists:
            return agent._process_applicant(connection,minio_client,app_id,force)
        execution=Execution(connection,app_id,snapshot,version,retry_key)
        if execution.row['state']=='SUPERSEDED':raise StaleGeneration('This execution was superseded; prepare a new input/pipeline version')
        if execution.terminal:return execution.row['outcome'] or 'AI_VALIDATION_FAILED'
        try:
            outcome=agent._process_applicant(connection,minio_client,app_id,True,execution)
            if outcome=='SKIPPED':
                execution.finish_in_transaction(outcome)
                connection.commit()
            return outcome
        except BaseException as error:
            execution.interrupted(error)
            raise

def run_batch(agent,connection,minio_client,app_ids=None,event_id=None,batch_id=None,force=False,retry_key=None):
    ensure_schema(connection)
    version=agent.generation_pipeline_version()
    with connection.cursor(cursor_factory=RealDictCursor) as q:
        if batch_id:
            q.execute('SELECT * FROM generation_batches WHERE id=%s',(batch_id,));batch=q.fetchone()
            if not batch:raise ValueError('Generation batch not found')
            if batch['pipeline_version']!=version:raise StaleGeneration('Pipeline changed; create a new batch instead of resuming old sections')
        else:
            if event_id:
                q.execute("SELECT result,effects,delivery_summary,manifest FROM ingestion_batch_events WHERE id=%s AND state='COMPLETED'",(event_id,))
                event=q.fetchone()
                if not event:raise ValueError('Ingestion event is not durably completed')
                if not event['effects'].get('objects_verified') or not event['manifest'].get('require_objects') or not event['manifest'].get('require_postgres'):
                    raise ValueError('Batch receipt did not confirm the shared PostgreSQL/MinIO handoff')
                if event['manifest']['config_hash']!=hashlib.sha256((agent.ROOT.parent/'policy/ingestion_rules.yaml').read_bytes()).hexdigest():
                    raise ValueError('Manifest rules changed; run intake under the current rules before generation')
                app_ids=event['result']['affected_ids']
            plan=[]
            for app_id in sorted(set(app_ids or [])):
                q.execute('SELECT 1 FROM applicants WHERE app_id=%s',(app_id,))
                plan.append({'app_id':app_id,'input_hash':input_hash(connection,app_id) if q.fetchone() else None})
            key=retry_key or ('force-'+str(uuid.uuid4()) if force else 'normal')
            identity=digest({'event_id':event_id,'plan':None if event_id else plan,'pipeline':version,'retry_key':key})
            q.execute("INSERT INTO generation_batches(identity_hash,ingestion_event_id,pipeline_version,retry_key) VALUES(%s,%s,%s,%s) ON CONFLICT(identity_hash) DO NOTHING",(identity,event_id,version,key))
            q.execute('SELECT * FROM generation_batches WHERE identity_hash=%s',(identity,));batch=q.fetchone()
            for member in plan:
                q.execute('INSERT INTO generation_batch_members(batch_id,app_id,input_hash) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(batch['id'],member['app_id'],member['input_hash']))
    connection.commit()
    batch_id=str(batch['id']);results={}
    print(f'Durable generation batch: {batch_id} (resume with --batch-id {batch_id})',flush=True)
    with exclusive(connection,'generation-batch:'+batch_id):
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as q:
                q.execute('SELECT * FROM generation_batch_members WHERE batch_id=%s ORDER BY app_id',(batch_id,));members=q.fetchall()
                q.execute("UPDATE generation_batches SET state='RUNNING',updated_at=now() WHERE id=%s",(batch_id,))
            connection.commit()
            for member in members:
                app_id=member['app_id']
                current=agent.get_applicant(connection,app_id)
                actual=input_hash(connection,app_id) if current else None
                connection.commit()
                if actual!=member['input_hash']:
                    state,outcome='STALE','INPUTS_CHANGED'
                elif member['state'] in {'DONE','FAILED','STALE','SKIPPED'}:
                    results[app_id]=member['outcome'];continue
                elif not current or current.get('officer_recommendation') or current.get('final_decision'):
                    state,outcome='SKIPPED','SKIPPED'
                else:
                    with connection.cursor() as q:q.execute("UPDATE generation_batch_members SET state='RUNNING',updated_at=now() WHERE batch_id=%s AND app_id=%s",(batch_id,app_id))
                    connection.commit()
                    try:
                        outcome=agent.process_applicant(connection,minio_client,app_id,batch['retry_key']!='normal',
                            generation_key=batch['retry_key'],expected_input_hash=member['input_hash'])
                        state='DONE' if outcome in GOOD else 'SKIPPED' if outcome=='SKIPPED' else 'FAILED'
                    except (GenerationBusy,StaleGeneration) as error:
                        if isinstance(error,GenerationBusy):raise
                        state,outcome='STALE','INPUTS_CHANGED'
                    except Exception:
                        # Infrastructure failures leave this member resumable, rather than
                        # converting an interrupted model call into a completed batch item.
                        connection.rollback()
                        with connection.cursor() as q:
                            q.execute("UPDATE generation_batch_members SET execution_id=(SELECT id FROM generation_executions WHERE app_id=%s AND input_hash=%s AND pipeline_version=%s AND retry_key=%s ORDER BY created_at DESC LIMIT 1),updated_at=now() WHERE batch_id=%s AND app_id=%s",
                                (app_id,member['input_hash'],version,batch['retry_key'],batch_id,app_id))
                        connection.commit()
                        results[app_id]='INTERRUPTED'
                        continue
                with connection.cursor() as q:
                    q.execute("UPDATE generation_batch_members SET state=%s,outcome=%s,updated_at=now(),execution_id=(SELECT id FROM generation_executions WHERE app_id=%s AND input_hash=%s AND pipeline_version=%s AND retry_key=%s ORDER BY created_at DESC LIMIT 1) WHERE batch_id=%s AND app_id=%s",
                        (state,outcome,app_id,member['input_hash'],version,batch['retry_key'],batch_id,app_id))
                connection.commit();results[app_id]=outcome
            with connection.cursor() as q:
                q.execute("SELECT count(*) FILTER(WHERE state IN ('PENDING','RUNNING')),count(*) FILTER(WHERE state IN ('FAILED','STALE')) FROM generation_batch_members WHERE batch_id=%s",(batch_id,))
                pending,failed=q.fetchone()
                q.execute('UPDATE generation_batches SET state=%s,updated_at=now() WHERE id=%s',('INTERRUPTED' if pending else 'NEEDS_ATTENTION' if failed else 'COMPLETED',batch_id))
            connection.commit()
        except BaseException:
            if not connection.closed:
                connection.rollback()
                with connection.cursor() as q:q.execute("UPDATE generation_batches SET state='INTERRUPTED',updated_at=now() WHERE id=%s",(batch_id,))
                connection.commit()
            raise
    return batch_id,results

def inspect_batch(connection,batch_id,object_client=None):
    with connection.cursor(cursor_factory=RealDictCursor) as q:
        q.execute('SELECT * FROM generation_batches WHERE id=%s',(batch_id,));batch=q.fetchone()
        if not batch:return None
        q.execute("""SELECT m.*,a.status AS applicant_status,a.officer_recommendation,a.final_decision,
          e.state AS execution_state,COALESCE(e.final_run_id,r.generation_run_id) AS final_run_id,e.review_request_id,r.state AS review_state,
          d.publication_request_id,(SELECT count(*) FROM dossier_publication_receipts p WHERE p.request_id=r.id) AS receipts,
          (SELECT jsonb_object_agg(s.section,jsonb_build_object('attempts',jsonb_array_length(s.attempts),'passed',s.errors='[]'::jsonb))
             FROM generation_section_checkpoints s WHERE s.execution_id=e.id) AS section_checkpoints,
          a.documents FROM generation_batch_members m JOIN generation_batches b ON b.id=m.batch_id
          LEFT JOIN applicants a ON a.app_id=m.app_id
          LEFT JOIN generation_executions e ON e.id=m.execution_id OR (m.execution_id IS NULL AND e.app_id=m.app_id AND e.input_hash=m.input_hash AND e.pipeline_version=b.pipeline_version AND e.retry_key=b.retry_key)
          LEFT JOIN applicant_dossier d ON d.app_id=m.app_id
          LEFT JOIN dossier_review_requests r ON r.id=COALESCE(e.review_request_id,d.publication_request_id)
          WHERE m.batch_id=%s ORDER BY m.app_id""",(batch_id,))
        members=[dict(row) for row in q.fetchall()]
    connection.commit()
    if object_client:
        for member in members:
            objects=[]
            for doc in member.get('documents') or []:
                item={'bucket':doc.get('minio_bucket') or doc.get('bucket'),'key':doc.get('minio_key') or doc.get('object_key'),
                    'expected_sha256':doc.get('sha256') or doc.get('sha256_checksum')}
                try:
                    response=object_client.get_object(item['bucket'],item['key'])
                    try:
                        checksum=hashlib.sha256()
                        for block in response.stream(1024*1024):checksum.update(block)
                        item.update(exists=True,actual_sha256=checksum.hexdigest(),matches=checksum.hexdigest()==str(item['expected_sha256']).lower())
                    finally:response.close();response.release_conn()
                except Exception as error:item.update(exists=False,matches=False,error=type(error).__name__)
                objects.append(item)
            member['objects']=objects
            member['objects_verified']=all(obj['matches'] for obj in objects) if objects else None
    return {'batch':dict(batch),'members':members}
