"""Content-addressed ingestion receipts for the shared PostgreSQL receiver."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy import create_engine

MIGRATION=Path(__file__).resolve().parents[1]/'storage/migrations/20261101_durable_batch_generation.sql'
ROOT=MIGRATION.parents[2]

class BatchBusy(RuntimeError): pass

def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def describe_event(source,config,scope,storage,require_objects,require_postgres,retry_key=None):
    source=Path(source)
    if not source.is_dir():raise FileNotFoundError(f'Batch directory not found: {source}')
    files=[{'path':p.relative_to(source).as_posix(),'sha256':file_hash(p)} for p in sorted(source.rglob('*'))
        if p.is_file() and not any(part.startswith('.') for part in p.relative_to(source).parts)]
    code=['ingestion/batch_ingest.py','ingestion/run_ingestion_check.py','ingestion/batch_events.py',
        'ingestion/validation/manifest_gate.py','storage/storage_manager.py','storage/models.py','storage/gpa_utils.py',
        'storage/migrations/20261101_durable_batch_generation.sql']
    manifest={'files':files,'config_hash':file_hash(config),'scope':sorted(scope) if scope is not None else None,
        'pipeline':{name:file_hash(ROOT/name) for name in code},'bucket':storage.minio_bucket,
        'object_endpoint':storage.minio_endpoint,'require_objects':require_objects,'require_postgres':require_postgres,'retry_key':retry_key}
    identity=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return identity,manifest

def verify_objects(storage,objects):
    if not storage.minio_available:return False
    for obj in objects:
        if not obj['sha256']:raise RuntimeError('Object checksum missing; handoff withheld')
        response=storage.minio_client.get_object(obj['bucket'],obj['key'])
        try:
            digest=hashlib.sha256()
            for block in response.stream(1024*1024):digest.update(block)
            if digest.hexdigest()!=str(obj['sha256']).lower():raise RuntimeError(f"Receiving object differs from saved batch: {obj['key']}; use the repair workflow")
        finally:
            response.close();response.release_conn()
    return True

class BatchEvent:
    def __init__(self,connection,storage,identity,manifest):
        self.connection=connection;self.storage=storage;self.manifest=manifest
        inserted=connection.execute(text("INSERT INTO ingestion_batch_events(event_hash,manifest) VALUES(:h,CAST(:m AS jsonb)) ON CONFLICT(event_hash) DO NOTHING RETURNING id"),{'h':identity,'m':json.dumps(manifest)}).first()
        self.row=dict(connection.execute(text('SELECT * FROM ingestion_batch_events WHERE event_hash=:h'),{'h':identity}).mappings().one())
        connection.commit()
        self.id=str(self.row['id']);self.staged=self.row['result'] is not None
        self.replayed=self.staged
        if not inserted and not self.staged:
            raise RuntimeError('Prior intake stopped before its receiver receipt; inspect the partial effects and use an explicit repair retry key, not an automatic replay')
    def verify(self):
        if self.staged:
            for app_id in self.row['effects']['applicants']:
                if not self.connection.execute(text('SELECT 1 FROM applicants WHERE app_id=:id'),{'id':app_id}).first():
                    raise RuntimeError('Receiving applicant row is missing; old batch will not be silently reapplied')
            verified=verify_objects(self.storage,self.row['effects']['objects'])
            if self.manifest['require_objects'] and not verified:raise RuntimeError('MinIO unavailable; saved receipt cannot confirm a new handoff')
            self.connection.commit()
    def stage(self,result,report,ingested):
        if not self.recheck_inputs():raise RuntimeError('Batch files changed during ingestion; handoff withheld')
        objects={}
        for app in ingested.applications:
            for doc in app.documents:
                objects[(doc.minio_bucket,doc.minio_key)]={'bucket':doc.minio_bucket,'key':doc.minio_key,'sha256':doc.sha256_checksum}
        for doc in ingested.orphans:
            objects[(self.storage.minio_bucket,doc['minio_key'])]={'bucket':self.storage.minio_bucket,'key':doc['minio_key'],'sha256':doc['sha256']}
        verified=verify_objects(self.storage,list(objects.values()))
        if self.manifest['require_objects'] and not verified:raise RuntimeError('MinIO effects are unconfirmed; no handoff')
        effects={'applicants':[app.applicant_id for app in ingested.applications],'objects':list(objects.values()),'objects_verified':verified}
        saved={**result.to_dict(),'orphans_count':len(ingested.orphans)}
        self.connection.execute(text("UPDATE ingestion_batch_events SET state='INGESTED',result=CAST(:r AS jsonb),report_text=:t,effects=CAST(:e AS jsonb),updated_at=now() WHERE id=:id"),
            {'id':self.id,'r':json.dumps(saved),'t':report,'e':json.dumps(effects)})
        self.connection.commit();self.row.update(result=saved,report_text=report,effects=effects);self.staged=True
    def complete(self,summary):
        self.connection.execute(text("UPDATE ingestion_batch_events SET state='COMPLETED',delivery_summary=CAST(:summary AS jsonb),last_error=NULL,updated_at=now() WHERE id=:id"),
            {'id':self.id,'summary':json.dumps(summary)})
        self.connection.commit();self.row['state']='COMPLETED'

@contextmanager
def ingestion_event(storage,source,config,scope,require_objects,require_postgres,retry_key=None):
    if not storage.db_available or storage.is_sqlite_fallback or storage.engine.dialect.name!='postgresql':
        yield None;return
    identity,manifest=describe_event(source,config,scope,storage,require_objects,require_postgres,retry_key)
    with storage.engine.connect() as connection:
        present=connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_class WHERE relname='ingestion_batch_events' AND relnamespace=current_schema()::regnamespace)")).scalar()
        connection.commit()
        if not present:connection.exec_driver_sql(MIGRATION.read_text(encoding='utf-8'));connection.commit()
        acquired=connection.execute(text("SELECT pg_try_advisory_lock(hashtext(current_schema()),hashtext('batch-ingestion'))")).scalar();connection.commit()
        if not acquired:raise BatchBusy('Another batch is ingesting; no work was duplicated. Retry after it finishes')
        event=None
        try:
            event=BatchEvent(connection,storage,identity,manifest)
            event.recheck_inputs=lambda:describe_event(source,config,scope,storage,require_objects,require_postgres,retry_key)[0]==identity
            event.verify()
            yield event
        except BaseException as error:
            connection.rollback()
            if event and event.row['state']!='COMPLETED':
                connection.execute(text("UPDATE ingestion_batch_events SET state=:state,last_error=:error,updated_at=now() WHERE id=:id"),
                    {'id':event.id,'state':'INTERRUPTED' if not isinstance(error,Exception) else 'FAILED','error':type(error).__name__})
                connection.commit()
            raise
        finally:
            connection.rollback()
            connection.execute(text("SELECT pg_advisory_unlock(hashtext(current_schema()),hashtext('batch-ingestion'))"));connection.commit()

def remember_summary(storage,event_id,summary):
    if not event_id:return
    with storage.engine.begin() as c:
        c.execute(text('UPDATE ingestion_batch_events SET delivery_summary=CAST(:summary AS jsonb) WHERE id=:id'),{'id':event_id,'summary':json.dumps(summary)})

def latest_summary(storage=None):
    engine=storage.engine if storage else None
    owned=False
    if engine is None:
        url=os.getenv('DATABASE_URL','')
        if not url.startswith('postgresql'):return None
        engine=create_engine(url,connect_args={'connect_timeout':3});owned=True
    try:
        with engine.connect() as c:
            if not c.execute(text("SELECT to_regclass('ingestion_batch_events')")).scalar():return None
            return c.execute(text("SELECT delivery_summary FROM ingestion_batch_events WHERE state='COMPLETED' AND delivery_summary IS NOT NULL ORDER BY updated_at DESC LIMIT 1")).scalar()
    except Exception as error:
        raise RuntimeError('Durable batch status is unavailable; check PostgreSQL') from error
    finally:
        if owned:engine.dispose()
