"""Actual PostgreSQL receiver effects, using a disposable isolated schema."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ai_agent import summarizing_agent as agent
from ai_agent.review_checkpoint import MIGRATION

pytestmark = pytest.mark.skipif(not os.getenv("POSTGRES_DB"), reason="Requires configured test PostgreSQL")


@pytest.fixture
def checkpoint_db(request):
    import psycopg2
    from psycopg2 import sql
    settings = dict(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])
    schema = "checkpoint_test_" + uuid.uuid4().hex
    owner = psycopg2.connect(**settings); owner.autocommit = True
    with owner.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def connect():
        c = psycopg2.connect(**settings, options=f"-c search_path={schema},public")
        return c
    connection = connect()
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE applicants (app_id varchar(10) PRIMARY KEY,status varchar(32),officer_recommendation text,final_decision text,documents jsonb DEFAULT '[]',superscored_sat_score integer,updated_at timestamptz DEFAULT now())")
        cursor.execute("INSERT INTO applicants(app_id,status) VALUES ('APP_050','READY_FOR_REVIEW')")
        cursor.execute("CREATE TABLE policy_chunks(policy_id text PRIMARY KEY,content text)")
    connection.commit()
    agent.ensure_output_tables(connection)
    with connection.cursor() as cursor:
        cursor.execute(MIGRATION.read_text())
        cursor.execute(MIGRATION.read_text())
    connection.commit()
    try:
        yield connection, connect
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            snapshot = {}
            for table, fields in [
                ("applicants", "app_id,status"),
                ("dossier_review_requests", "id,app_id,state,candidate_hash,generation_run_id"),
                ("applicant_dossier", "app_id,publication_request_id"),
                ("dossier_publication_receipts", "request_id,app_id,candidate_hash"),
            ]:
                cursor.execute(sql.SQL("SELECT {} FROM {}").format(sql.SQL(fields), sql.Identifier(table)))
                snapshot[table] = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
            request.node.user_properties.append(("receiver_snapshot", json.dumps(snapshot, default=str)))
        connection.close()
        with owner.cursor() as cursor:
            assert schema.startswith("checkpoint_test_")
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        owner.close()


def candidate():
    return {"app_id": "APP_050", **{key: {} for key in agent.JSON_COLUMNS},
        "strengths": [], "review_notes": [], "policy_assessment": [], "evidence_map": [], "holistic_assessment": "Advisory factual summary."}


def stage(c, payload=None, seconds=86400, scanned=False, routed=False):
    from psycopg2.extras import Json
    payload = payload or candidate()
    with c.cursor() as cursor:
        cursor.execute("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES ('APP_050','REVIEW_PENDING',%s) RETURNING id", (Json({"passed": True, "requires_human_verification": scanned}),))
        run_id = cursor.fetchone()[0]
        cursor.execute("SELECT checkpoint_input_snapshot('APP_050')")
        snapshot = cursor.fetchone()[0]
        function = "route_dossier_candidate" if routed else "stage_dossier_review"
        cursor.execute(f"SELECT {function}('APP_050',%s,%s,%s,'pipeline-v1',%s)",
            (run_id, Json(payload), Json(snapshot), datetime.now(timezone.utc)+timedelta(seconds=seconds)))
        review = cursor.fetchone()[0]
    c.commit()
    return review


def decide(c, r, decision="APPROVE", confirm=True, evidence=True, commit=True, digest=None):
    with c.cursor() as cursor:
        cursor.execute("SELECT decide_dossier_review(%s,%s,'PUBLISH_ADVISORY_DOSSIER',%s,'Officer demo','Checked the cited sources',%s,%s)",
            (r["id"], digest or r["candidate_hash"], decision, confirm, evidence))
        result = cursor.fetchone()[0]
    if commit: c.commit()
    return result


def count(c, table):
    from psycopg2 import sql
    with c.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        return cursor.fetchone()[0]


def test_approved_publication_and_duplicate_receipt(checkpoint_db):
    c, _ = checkpoint_db
    r = stage(c)
    assert count(c, "applicant_dossier") == 0
    assert decide(c, r, confirm=False)["status"] == 400
    assert decide(c, r, decision=None)["status"] == 400
    assert decide(c, r, digest="wrong-version")["status"] == 409
    result = decide(c, r)
    assert result["request"]["state"] == "PUBLISHED" and result["receipt"]["candidate_hash"] == r["candidate_hash"]
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == 1
    assert decide(c, r)["replayed"] is True
    assert decide(c, r, decision="REJECT")["status"] == 409
    with c.cursor() as cursor:
        cursor.execute("SELECT publication_request_id,holistic_assessment FROM applicant_dossier")
        assert cursor.fetchone() == (r["id"], candidate()["holistic_assessment"])
    assert count(c, "dossier_publication_receipts") == 1


def test_rejection_and_duplicate_staging_withhold_publication(checkpoint_db):
    c, _ = checkpoint_db
    r = stage(c)
    assert stage(c)["id"] == r["id"]
    assert count(c, "dossier_review_requests") == 1
    assert decide(c, r, decision="REJECT")["request"]["state"] == "REJECTED"
    assert decide(c, r, decision="REJECT")["replayed"]
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == 0


def test_expiry_escalates_and_late_approval_fails(checkpoint_db):
    c, _ = checkpoint_db
    r = stage(c, seconds=.1)
    with c.cursor() as cursor: cursor.execute("SELECT pg_sleep(.15)")
    result = decide(c, r)
    assert result["status"] == 409 and result["request"]["state"] == "ESCALATED"
    assert result["request"]["escalation_owner"] == "Senior admissions counselor"
    assert count(c, "dossier_publication_receipts") == 0


@pytest.mark.parametrize("change", ["UPDATE applicants SET superscored_sat_score=1550", "INSERT INTO policy_chunks VALUES ('POL-NEW','Changed rule')"])
def test_source_or_policy_changes_invalidate_authorization(checkpoint_db, change):
    c, _ = checkpoint_db
    r = stage(c)
    with c.cursor() as cursor: cursor.execute(change)
    c.commit()
    result = decide(c, r)
    assert result["status"] == 409 and result["request"]["state"] == "SUPERSEDED"
    assert count(c, "dossier_publication_receipts") == 0


def test_restart_interrupted_transaction_and_lost_confirmation(checkpoint_db):
    c, connect = checkpoint_db
    r = stage(c)
    second = connect()
    try:
        with second.cursor() as cursor:
            cursor.execute("SELECT state FROM dossier_review_requests WHERE id=%s", (r["id"],))
            assert cursor.fetchone()[0] == "REVIEW_PENDING"
        assert decide(second, r, commit=False)["status"] == 200
    finally:
        second.close()  # interrupted before commit: publication rolls back
    assert count(c, "applicant_dossier") == 0
    third = connect()
    decide(third, r)  # commit succeeds, but pretend its response was lost
    third.close()
    fourth = connect()
    try:
        assert decide(fourth, r)["replayed"] is True
        assert count(fourth, "dossier_publication_receipts") == 1
    finally: fourth.close()


def test_scanned_evidence_and_immutable_content(checkpoint_db):
    c, _ = checkpoint_db
    r = stage(c, scanned=True)
    assert decide(c, r, evidence=False)["status"] == 400
    with pytest.raises(Exception, match="immutable"):
        with c.cursor() as cursor: cursor.execute("UPDATE dossier_review_requests SET candidate=candidate || '{\"tampered\":true}' WHERE id=%s", (r["id"],))
    c.rollback()
    assert decide(c, r, evidence=True)["status"] == 200


def test_receiver_failure_rolls_back_entire_approval(checkpoint_db):
    c, _ = checkpoint_db
    r = stage(c)
    with c.cursor() as cursor:
        cursor.execute("CREATE FUNCTION fail_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled receipt failure'; END $$")
        cursor.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON dossier_publication_receipts FOR EACH ROW EXECUTE FUNCTION fail_receipt()")
    c.commit()
    with pytest.raises(Exception, match="controlled receipt failure"): decide(c, r)
    c.rollback()
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == 0
    with c.cursor() as cursor:
        cursor.execute("SELECT state FROM dossier_review_requests WHERE id=%s", (r["id"],))
        assert cursor.fetchone()[0] == "REVIEW_PENDING"


def test_new_candidate_supersedes_old_and_human_disposition_blocks_replacement(checkpoint_db):
    c, _ = checkpoint_db
    old = stage(c)
    changed = candidate(); changed["holistic_assessment"] = "Corrected factual summary."
    new = stage(c, changed)
    assert new["id"] != old["id"] and decide(c, old)["status"] == 409
    with c.cursor() as cursor: cursor.execute("UPDATE applicants SET officer_recommendation='WAITLIST',status='REVIEWED'")
    c.commit()
    assert decide(c, new)["status"] == 409
    assert count(c, "applicant_dossier") == 0


@pytest.mark.parametrize("flagged", [False, True])
def test_actual_generator_routes_and_reuses_saved_version(checkpoint_db, monkeypatch, tmp_path, flagged):
    c, connect = checkpoint_db
    def sample(schema):
        kind = schema["type"]
        if isinstance(kind, list): return None
        if kind == "object": return {key: sample(value) for key, value in schema["properties"].items()}
        if kind == "array": return []
        if kind == "string": return schema.get("enum", ["Factual advisory summary."])[0]
        return 0
    calls = []
    def model(prompt, schema, *args):
        calls.append(prompt)
        output = sample(schema)
        if flagged and "document_facts" in output:
            output["notes"] = [{"category": "unclear", "note": "Source reading requires verification."}]
        return json.dumps(output), {"seconds": 0, "output_tokens": 5}
    monkeypatch.setattr(agent, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(agent, "call_model", model)
    monkeypatch.setattr(agent, "retrieve_policies", lambda *args: [])
    monkeypatch.setattr(agent, "load_pages", lambda *args: ([{"document_type": "transcript", "filename": "transcript.pdf", "page_number": 1, "text": "Source text", "png_bytes": b"image"}], []))
    expected = "REVIEW_PENDING" if flagged else "DOSSIER_READY"
    assert agent.process_applicant(c, None, "APP_050") == expected
    assert len(calls) == 5  # no supplement in the controlled input
    assert count(c, "applicant_dossier") == (0 if flagged else 1)
    another = connect()
    with another.cursor() as cursor:
        cursor.execute("SELECT id,state FROM dossier_review_requests")
        review_id, state = cursor.fetchone()
        assert state == ("REVIEW_PENDING" if flagged else "PUBLISHED")
    another.close()
    with c.cursor() as cursor: cursor.execute("UPDATE applicants SET status='READY_FOR_REVIEW'")
    c.commit()
    assert agent.process_applicant(c, None, "APP_050") == expected
    assert len(calls) == 5 and count(c, "dossier_review_requests") == 1
    with c.cursor() as cursor:
        cursor.execute("SELECT candidate_hash FROM dossier_review_requests WHERE id=%s", (review_id,))
        digest = cursor.fetchone()[0]
    if flagged:
        assert decide(c, {"id": review_id, "candidate_hash": digest})["status"] == 200
    assert count(c, "applicant_dossier") == 1


def test_clean_candidate_is_available_without_inventing_human_approval(checkpoint_db):
    c, _ = checkpoint_db
    payload = candidate()
    payload["evidence_map"] = [{"verification_status": "TEXT_VERIFIED"}]
    r = stage(c, payload, routed=True)
    assert r["state"] == "PUBLISHED" and r["review_mode"] == "AUTOMATIC"
    assert r["decision"] is None and r["reviewer"] is None and r["decided_at"] is None
    assert stage(c, payload, routed=True)["id"] == r["id"]
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == 1
    assert decide(c, r)["status"] == 409


@pytest.mark.parametrize("kind", ["conflict", "unclear_policy", "image", "unknown_evidence"])
def test_identified_exceptions_are_withheld_by_routing(checkpoint_db, kind):
    c, _ = checkpoint_db
    payload = candidate()
    if kind == "conflict": payload["review_notes"] = [{"note": "Source discrepancy: score sources differ"}]
    if kind == "unclear_policy": payload["policy_assessment"] = [{"alignment": "unclear"}]
    if kind in {"image", "unknown_evidence"}: payload["evidence_map"] = [{"verification_status": "UNVERIFIED_IMAGE_SOURCE" if kind == "image" else "NOT_VERIFIED"}]
    r = stage(c, payload, scanned=kind == "image", routed=True)
    assert r["state"] == "REVIEW_PENDING" and r["review_mode"] == "EXCEPTION"
    assert r["exception_reasons"]
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == 0
    with pytest.raises(Exception, match="immutable"):
        with c.cursor() as cursor: cursor.execute("UPDATE dossier_review_requests SET exception_reasons='[]' WHERE id=%s", (r["id"],))
    c.rollback()


def test_automatic_publication_failure_rolls_back_routing(checkpoint_db):
    c, _ = checkpoint_db
    with c.cursor() as cursor:
        cursor.execute("CREATE FUNCTION fail_auto_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled auto failure'; END $$")
        cursor.execute("CREATE TRIGGER fail_auto_receipt BEFORE INSERT ON dossier_publication_receipts FOR EACH ROW EXECUTE FUNCTION fail_auto_receipt()")
    c.commit()
    with pytest.raises(Exception, match="controlled auto failure"): stage(c, routed=True)
    c.rollback()
    assert count(c, "applicant_dossier") == count(c, "dossier_publication_receipts") == count(c, "dossier_review_requests") == 0


def test_concurrent_approvals_have_one_effect(checkpoint_db):
    from concurrent.futures import ThreadPoolExecutor
    c, connect = checkpoint_db
    r = stage(c)
    def approve():
        connection = connect()
        try: return decide(connection, r)
        finally: connection.close()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: approve(), range(2)))
    assert all(result["status"] == 200 for result in results)
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert count(c, "dossier_publication_receipts") == 1


def test_staging_refuses_inputs_changed_since_generation(checkpoint_db):
    from psycopg2.extras import Json
    c, _ = checkpoint_db
    with c.cursor() as cursor:
        cursor.execute("SELECT checkpoint_input_snapshot('APP_050')")
        old = cursor.fetchone()[0]
        cursor.execute("UPDATE applicants SET superscored_sat_score=1599")
        cursor.execute("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES ('APP_050','REVIEW_PENDING','{\"passed\":true}') RETURNING id")
        run_id = cursor.fetchone()[0]
    c.commit()
    with pytest.raises(Exception, match="Inputs changed"):
        with c.cursor() as cursor:
            cursor.execute("SELECT stage_dossier_review('APP_050',%s,%s,%s,'v1',clock_timestamp()+interval '1 day')", (run_id,Json(candidate()),Json(old)))
    c.rollback()
    assert count(c, "dossier_review_requests") == count(c, "applicant_dossier") == 0


def test_policy_cannot_change_between_approval_check_and_commit(checkpoint_db):
    c, connect = checkpoint_db
    with c.cursor() as cursor: cursor.execute("INSERT INTO policy_chunks VALUES ('POL-001','Original rule')")
    c.commit()
    r = stage(c)
    assert decide(c, r, commit=False)["status"] == 200
    writer = connect()
    try:
        with writer.cursor() as cursor:
            cursor.execute("SET lock_timeout='50ms'")
            with pytest.raises(Exception, match="lock timeout"):
                cursor.execute("UPDATE policy_chunks SET content='Changed rule'")
        writer.rollback()
        c.commit()
        with writer.cursor() as cursor: cursor.execute("UPDATE policy_chunks SET content='Changed rule'")
        writer.commit()
    finally: writer.close()
    assert count(c, "dossier_publication_receipts") == 1
