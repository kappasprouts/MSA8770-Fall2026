"""Durable, explicitly requested IT retries. No work starts from a queue read.

Run ``python -m ingestion.it_retry_worker --watch``. A dead worker's RUNNING job
becomes NEEDS_RECHECK, never silently QUEUED again. Case/job updates are atomic;
model/MinIO work has its own existing receiving-system transactions.
"""
import argparse
import os
from pathlib import Path
import threading
import uuid

from psycopg2.extras import Json, RealDictCursor

from ai_agent import summarizing_agent as agent

MIGRATION = Path(__file__).resolve().parents[1] / "storage/migrations/20261101_it_exception_actions.sql"
GOOD = {"DOSSIER_READY", "REVIEW_PENDING"}
BAD = {"ERROR", "PROCESSING_ERROR", "AGENT_ERROR", "AI_VALIDATION_FAILED", "HUMAN_REVIEW_AI_FAILED"}


def ensure_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))


def heartbeat(connection, worker_id, ingestion_enabled):
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO it_retry_workers(id,last_seen,ingestion_enabled) VALUES(%s,now(),%s) ON CONFLICT(id) DO UPDATE SET last_seen=now(),ingestion_enabled=EXCLUDED.ingestion_enabled", (worker_id,ingestion_enabled))
    connection.commit()


def recover_interrupted(connection):
    with connection.cursor() as cursor:
        cursor.execute("""UPDATE it_retry_jobs j SET state='NEEDS_RECHECK',result='{"message":"Worker stopped or heartbeat expired; verify receiver before another retry"}'::jsonb
          WHERE state='RUNNING' AND NOT EXISTS(SELECT 1 FROM it_retry_workers w WHERE w.id=j.worker_id AND w.last_seen>now()-interval '45 seconds')""")
    connection.commit()


def claim_job(connection, worker_id, ingestion_enabled=False):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""SELECT * FROM it_retry_jobs WHERE state='QUEUED' AND (source='SUMMARIZER' OR %s)
          ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1""", (ingestion_enabled,))
        job = cursor.fetchone()
        if job:
            # Held by this database session throughout external work; another worker cannot
            # retry the same applicant even after an uncertain heartbeat interruption.
            cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired", ("it-retry:"+job["applicant_id"],))
            if not cursor.fetchone()["acquired"]:
                connection.rollback()
                return None
            cursor.execute("UPDATE it_retry_jobs SET state='RUNNING',worker_id=%s,started_at=now() WHERE id=%s", (worker_id,job["id"]))
    connection.commit()
    return dict(job) if job else None


def receiver_snapshot(connection, app_id):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""SELECT a.status,a.officer_recommendation,a.final_decision,
          encode(sha256(convert_to(checkpoint_input_snapshot(a.app_id)::text,'UTF8')),'hex') AS source_version,
          g.id AS run_id,g.run_status,g.validation,r.id AS request_id,r.state AS review_state,
          r.input_snapshot=checkpoint_input_snapshot(a.app_id) AS fresh,
          d.publication_request_id
          FROM applicants a LEFT JOIN LATERAL(SELECT * FROM dossier_generation_runs WHERE app_id=a.app_id ORDER BY created_at DESC,id DESC LIMIT 1) g ON true
          LEFT JOIN dossier_review_requests r ON r.generation_run_id=g.id
          LEFT JOIN applicant_dossier d ON d.app_id=a.app_id WHERE a.app_id=%s""", (app_id,))
        return dict(cursor.fetchone() or {})


def run_summarizer(connection, job):
    return agent.process_applicant(connection,agent.connect_minio(),job["applicant_id"],force=True,generation_key="it-job:"+str(job["id"]),expected_input_hash=job["source_version"])


def run_ingestion(connection, job):
    from ingestion.pipeline import BatchIngestionPipeline
    if not os.getenv("INGESTION_INPUT_DIR"):
        raise RuntimeError("An explicit INGESTION_INPUT_DIR is required; no default batch retry")
    # The gate must write to the same receiver the job was authorized against.
    from sqlalchemy.engine import URL
    from storage.storage_manager import StorageManager
    params=connection.get_dsn_parameters()
    database_url=URL.create("postgresql+psycopg",username=params["user"],password=os.getenv("POSTGRES_PASSWORD","postgres"),
        host=params["host"],port=int(params["port"]),database=params["dbname"]).render_as_string(hide_password=False)
    result = BatchIngestionPipeline(storage_manager=StorageManager(database_url=database_url)).process_packet(job["applicant_id"],retry_key="it-job:"+str(job["id"]))
    if not result or result.get("status") in BAD:
        return {"verified":False,"message":"Packet retry still requires technical attention"}
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("""SELECT a.status,l.id AS manifest_audit_id,l.details->>'processing_status' AS gate_status,
          encode(sha256(convert_to(checkpoint_input_snapshot(a.app_id)::text,'UTF8')),'hex') AS source_version
          FROM applicants a JOIN LATERAL(SELECT id,details FROM audit_logs WHERE applicant_id=a.app_id
          AND action='MANIFEST_EVALUATED' ORDER BY created_at DESC,id DESC LIMIT 1) l ON true WHERE a.app_id=%s""",(job["applicant_id"],))
        saved = dict(cursor.fetchone() or {})
    return {"verified":saved.get("gate_status")==result["status"] and result["status"] in {"READY_FOR_REVIEW","INCOMPLETE","AWAITING_MATERIALS"}
        and result.get("hard_stop") is True and result.get("storage_mode")=="postgresql" and result.get("object_storage_required") is True,
        "receiver":saved,"handoff_ready":result.get("handoff_ready",False),"message":"Packet checks rerun; dossier generation remains a separate step"}


def finish_job(connection, job, state, result):
    connection.rollback()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM applicants WHERE app_id=%s FOR UPDATE",(job["applicant_id"],))
        cursor.execute("LOCK TABLE policy_chunks IN SHARE MODE")
        if state=="SUCCEEDED":
            current_receiver=receiver_snapshot(connection,job["applicant_id"])
            valid = validated_receiver(job,current_receiver) if job["source"]=="SUMMARIZER" else (
                current_receiver.get("source_version")==result.get("receiver",{}).get("source_version") and current_receiver.get("status") not in BAD)
            if not valid:
                state="NEEDS_RECHECK"
                result={"verified":False,"message":"Receiver changed before the result commit; recheck the saved outcome"}
        cursor.execute("SELECT state FROM it_retry_jobs WHERE id=%s FOR UPDATE",(job["id"],))
        current = cursor.fetchone()[0]
        if current not in {"RUNNING","NEEDS_RECHECK"}:
            return
        cursor.execute("UPDATE it_retry_jobs SET state=%s,finished_at=now(),result=%s WHERE id=%s",(state,Json(result),job["id"]))
        case_state = "RESOLVED" if state=="SUCCEEDED" else "SUPERSEDED" if result.get("new_failure_run_id") else "IN_PROGRESS"
        cursor.execute("UPDATE it_exception_cases SET state=%s,revision=revision+1,updated_at=now(),resolution_evidence=%s WHERE id=%s",(case_state,Json(result),job["case_id"]))
        cursor.execute("""INSERT INTO audit_logs(id,applicant_id,action,actor,details,created_at)
          VALUES(%s,%s,'IT_EXCEPTION_RETRY_FINISHED','it_retry_worker',%s,now())""",(str(uuid.uuid4()),job["applicant_id"],Json({"job_id":str(job["id"]),"state":state,**result})))
    connection.commit()


def validated_receiver(job, after):
    return bool(after.get("run_id") and after["run_id"]>job["failure_run_id"] and
        after.get("run_status") in GOOD and (after.get("validation") or {}).get("passed") is True and
        after.get("fresh") and (after.get("review_state")=="REVIEW_PENDING" or
        (after.get("review_state")=="PUBLISHED" and after.get("publication_request_id")==after.get("request_id"))))


def execute_job(connection, job, summarizer=run_summarizer, ingestion=run_ingestion):
    try:
        before = receiver_snapshot(connection,job["applicant_id"])
        connection.commit()
        if not before or before.get("officer_recommendation") or before.get("final_decision") or before["source_version"]!=job["source_version"]:
            finish_job(connection,job,"STALE",{"verified":False,"message":"Applicant inputs or human disposition changed; retry withheld"})
            return
        if job["source"]=="SUMMARIZER":
            if str(before.get("run_id"))!=str(job["failure_run_id"]) or before.get("run_status") not in BAD:
                finish_job(connection,job,"STALE",{"verified":False,"message":"A newer generation exists; inspect its saved outcome"})
                return
            summarizer(connection,job)
            after = receiver_snapshot(connection,job["applicant_id"])
            success = validated_receiver(job,after)
            evidence = {"verified":success,"generation_run_id":after.get("run_id"),"run_status":after.get("run_status"),
                "request_id":str(after["request_id"]) if after.get("request_id") else None,
                "review_state":after.get("review_state"),"message":"Validated receiver confirmed; any admissions exceptions still need officer resolution" if success else "No new validated receiver outcome; technical issue remains"}
            if not success and after.get("run_id")!=before.get("run_id"):
                evidence["new_failure_run_id"]=after.get("run_id")
        else:
            if before.get("status") not in BAD:
                finish_job(connection,job,"STALE",{"verified":False,"message":"Applicant no longer has this ingestion failure"})
                return
            evidence = ingestion(connection,job)
        finish_job(connection,job,"SUCCEEDED" if evidence.get("verified") else "FAILED",evidence)
    except Exception as exc:
        connection.rollback()
        # A result-save error can follow a committed dossier effect. Check the
        # receiver before describing the retry as failed or repeating any work.
        after=receiver_snapshot(connection,job["applicant_id"])
        if job["source"]=="SUMMARIZER" and validated_receiver(job,after):
            finish_job(connection,job,"SUCCEEDED",{"verified":True,"message":"Recovered the validated receiving-system outcome after an interrupted confirmation",
                "generation_run_id":after["run_id"],"request_id":str(after["request_id"]),"review_state":after["review_state"]})
            return
        # Avoid returning raw source content or connection credentials to the UI.
        finish_job(connection,job,"FAILED",{"verified":False,"message":f"Retry failed ({type(exc).__name__}); inspect service logs and correct the source or service"})
    finally:
        connection.rollback()
        with connection.cursor() as cursor: cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))",("it-retry:"+job["applicant_id"],))
        connection.commit()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch",action="store_true")
    parser.add_argument("--schema",action="store_true")
    args=parser.parse_args()
    connection=agent.connect_postgres()
    if args.schema:
        ensure_schema(connection); connection.close(); return
    worker_id=str(uuid.uuid4())
    enabled=bool(os.getenv("INGESTION_INPUT_DIR"))
    stop=threading.Event()
    def pulse():
        while not stop.is_set():
            try:
                c=agent.connect_postgres()
                try: heartbeat(c,worker_id,enabled)
                finally: c.close()
            except Exception:
                pass
            stop.wait(10)
    thread=threading.Thread(target=pulse,daemon=True); thread.start()
    print(f"IT retry worker ready (ingestion retries {'enabled' if enabled else 'disabled: no explicit input directory'})",flush=True)
    try:
        while True:
            heartbeat(connection,worker_id,enabled); recover_interrupted(connection)
            job=claim_job(connection,worker_id,enabled)
            if job: execute_job(connection,job)
            if not args.watch: break
            stop.wait(2)
    finally:
        stop.set(); thread.join(timeout=2)
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM it_retry_workers WHERE id=%s",(worker_id,))
        connection.commit(); connection.close()


if __name__=="__main__": main()
