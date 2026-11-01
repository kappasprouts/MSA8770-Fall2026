import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { isItActionable } from "../src/lib/it-exceptions.mjs";

const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const loaded = { exports: {} };
  new Function("require", "module", "exports", compiled)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loaded, loaded.exports);
  return loaded.exports;
}

const display = load("../src/lib/exception-display.ts");
const wrapper = ({ children }) => React.createElement("div", {}, children);
const aliases = {
  "./eaos.module.css": { default: {} }, "./exceptions.module.css": { default: {} },
  "@/lib/exception-display": display, "@/lib/http": {},
  "./WorkspaceIcon": { default: () => null },
  "./RequestState": { default: ({ title, description }) => React.createElement("div", {}, title, description) },
  "./ItCaseActions": { default: () => React.createElement("section", {}, "Manage technical issue") },
};
function* elements(value) {
  if (Array.isArray(value)) { for (const child of value) yield* elements(child); }
  else if (React.isValidElement(value)) { yield value; yield* elements(value.props.children); }
}
function panel(path, states, props = {}) {
  let cursor = 0;
  const Component = load(path, { ...aliases, react: {
    ...React, useEffect() {}, useMemo: callback => callback(), useRef: value=>({current:value}),
    useState() {
      const index = cursor++;
      return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
    },
  } }).default;
  function render() { cursor = 0; return Component(props); }
  return {
    all: () => [...elements(render())],
    find: predicate => [...elements(render())].find(predicate),
    html: () => renderToStaticMarkup(render()),
  };
}
const record = (id, extra = {}) => ({
  id, applicantId: id, applicantName: `Example ${id}`, intendedMajor: "Biology", status: "AI_VALIDATION_FAILED",
  category: "AI Validation Failure", severity: "HIGH", source: "SUMMARIZER", summary: "Citation mismatch",
  findings: ["Unsupported citation"], affectedDocuments: ["transcript.pdf"], updatedAt: null, hasDossier: true,
  auditHistory: [{ action: "AI_VALIDATION_FAILED", actor: "summarizing_agent", createdAt: "2026-10-31T12:00:00Z" }], ...extra,
});

test("queue search includes affected documents, combines filters, and opens the matching exception", () => {
  const rows = [record("APP_A"), record("APP_B", { severity: "LOW", affectedDocuments: ["essay.pdf"] }),
    record("orphan-1", { applicantId: null, source: "ORPHAN_INTAKE", severity: "MEDIUM", category: "Orphan Document" })];
  let selected;
  const view = panel("../src/components/ErrorQueuePanel.tsx", [rows, false, "", "", "ALL", "ALL", 0, "ACTIVE"], { onViewDetails: id => { selected = id; } });
  const ids = () => view.all().filter(node => node.type === "tr" && node.key).map(node => node.key);
  assert.equal(ids().length, 3);
  view.find(node => node.type === "input").props.onChange({ target: { value: " essay.pdf " } });
  assert.deepEqual(ids(), ["APP_B"]);
  view.find(node => node.props["aria-label"] === "View details for APP_B").props.onClick();
  assert.equal(selected, "APP_B");
  view.find(node => node.type === "input").props.onChange({ target: { value: "" } });
  view.find(node => node.props["aria-label"] === "Filter by category").props.onChange({ target: { value: "AI Validation Failure" } });
  view.find(node => node.props["aria-label"] === "Filter by priority").props.onChange({ target: { value: "HIGH" } });
  assert.deepEqual(ids(), ["APP_A"]);
  view.find(node => node.props["aria-label"] === "Filter by priority").props.onChange({ target: { value: "CRITICAL" } });
  assert.match(view.html(), /No exceptions match these filters/);
});

test("queue distinguishes loading, outages, and a true empty queue without showing stale rows", () => {
  const view = (rows, loading, error) => panel("../src/components/ErrorQueuePanel.tsx", [rows, loading, error, "", "ALL", "ALL", 0, "ACTIVE"]);
  assert.match(view([], true, "").html(), /Loading exception records/);
  assert.match(view([], false, "").html(), /No IT system errors found/);
  const failed = view([record("STALE")], false, "Service unavailable");
  assert.match(failed.html(), /The error queue could not be loaded/);
  assert.doesNotMatch(failed.html(), /Example STALE/);
  assert.match(failed.html(), /<strong>—<\/strong>/);
  failed.find(node => node.type === "button" && node.props.children === "Refresh queue").props.onClick();
  assert.match(failed.html(), /Loading exception records/);
});

test("details retain findings, documents, audit history, back navigation, and conditional dossier access", () => {
  let opened;
  let backed = false;
  const props = { exceptionId: "APP_A", onBack: () => { backed = true; }, onOpenApplicant: id => { opened = id; } };
  const row = record("APP_A", { findings: ["Unsafe <script> content", "x".repeat(200)] });
  const view = panel("../src/components/ApplicantExceptionDetails.tsx", [row, false, "", 0], props);
  assert.match(view.html(), /Unsafe &lt;script&gt; content/);
  for (const text of ["Validation findings", "transcript.pdf", "Audit history", "summarizing_agent"]) assert.ok(view.html().includes(text));
  view.find(node => node.type === "button" && node.props.children === "Open available applicant dossier").props.onClick();
  assert.equal(opened, "APP_A");
  view.find(node => node.type === "button" && node.props.children !== "Open available applicant dossier").props.onClick();
  assert.equal(backed, true);
  const orphan = panel("../src/components/ApplicantExceptionDetails.tsx", [record("orphan", { applicantId: null, hasDossier: false, findings: [], affectedDocuments: [], auditHistory: [] }), false, "", 0], props);
  assert.doesNotMatch(orphan.html(), /Open available applicant dossier/);
  assert.match(orphan.html(), /No audit events are available/);
  assert.match(panel("../src/components/ApplicantExceptionDetails.tsx", [null, false, "Exception missing", 0], props).html(), /Exception details unavailable/);
});

test("nested exception routes keep IT navigation active and preserve all existing workspaces", () => {
  const Shell = load("../src/components/EaosShell.tsx", {
    "next/image": { default: ({ src, alt }) => React.createElement("img", { src, alt }) },
    "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
    "next/navigation": { usePathname: () => "/error-queue/applicant-APP_A-summarizer", useRouter: () => ({}) },
    "./eaos.module.css": { default: {} }, "./Logo": { default: () => null }, "./WorkspaceIcon": { default: () => null },
  }).default;
  const html = renderToStaticMarkup(React.createElement(Shell, { title: "Exception Details", subtitle: "", role: "IT administrator" }));
  for (const label of ["Home", "Processing Dashboard", "Applicant Review", "Final Decisions", "Summary Statistics", "IT Error Queue"]) assert.ok(html.includes(`aria-label="${label}"`));
  assert.equal((html.match(/aria-current="page"/g) ?? []).length, 1);
  assert.match(html, /href="\/error-queue" aria-current="page"/);
  assert.match(html, /src="\/rsu-sidebar-building.png"/);
  assert.match(html, /aria-label="Collapse sidebar"/);
  assert.doesNotMatch(html, /coming soon/i);
});

test("sidebar starts expanded and can collapse to the icon rail", () => {
  let collapsed = false;
  const Shell = load("../src/components/EaosShell.tsx", {
    react: { ...React, useState: () => [collapsed, value => { collapsed = typeof value === "function" ? value(collapsed) : value; }] },
    "next/image": { default: ({ src, alt }) => React.createElement("img", { src, alt }) },
    "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
    "next/navigation": { usePathname: () => "/applicant-review", useRouter: () => ({}) },
    "./eaos.module.css": { default: {} }, "./Logo": { default: () => null }, "./WorkspaceIcon": { default: () => null },
  }).default;
  const props = { title: "Applicant Review", subtitle: "", role: "Applicant review" };
  const render = () => Shell(props);
  const button = () => [...elements(render())].find(node => node.type === "button" && node.props["aria-label"]?.endsWith("sidebar"));
  assert.equal(button().props["aria-label"], "Collapse sidebar");
  assert.equal(button().props.children.props.name, "collapse");
  const nodes = [...elements(render())];
  assert.ok(nodes.findIndex(node => node.type === "nav") < nodes.findIndex(node => node.type === "button" && node.props["aria-label"] === "Collapse sidebar"));
  assert.match(renderToStaticMarkup(render()), /src="\/rsu-sidebar-building.png"/);
  button().props.onClick();
  assert.equal(button().props["aria-label"], "Expand sidebar");
  assert.doesNotMatch(renderToStaticMarkup(render()), /rsu-sidebar-building.png/);
  button().props.onClick();
  assert.equal(button().props["aria-label"], "Collapse sidebar");
});

test("queue and details routes encode IDs and use mi's canonical applicant link", () => {
  const pushed = [];
  const navigation = { useRouter: () => ({ push: path => pushed.push(path) }), useParams: () => ({ id: "exception A" }) };
  const http = load("../src/lib/http.ts");
  const review = load("../src/lib/review-state.ts");
  const recommendation = load("../src/lib/recommendation.ts");
  const api = load("../src/lib/eaos-api.ts", { "./http": http, "./review-state": review, "./recommendation": recommendation });
  const routeAliases = { "next/navigation": navigation, "@/components/EaosShell": { default: wrapper },
    "@/components/ErrorQueuePanel": { default: wrapper }, "@/components/ApplicantExceptionDetails": { default: wrapper }, "@/lib/eaos-api": api };
  const queue = load("../src/app/error-queue/page.tsx", routeAliases).default();
  queue.props.children.props.onViewDetails("orphan / A");
  assert.equal(pushed.pop(), "/error-queue/orphan%20%2F%20A");
  const detail = load("../src/app/error-queue/[id]/page.tsx", routeAliases).default().props.children;
  assert.equal(detail.key, "exception A");
  detail.props.onOpenApplicant("APP / A");
  assert.equal(pushed.pop(), "/applicant-review?appId=APP%20%2F%20A");
  detail.props.onBack();
  assert.equal(pushed.pop(), "/error-queue");
});

test("exception API preserves technical evidence and orphan records while excluding student-only findings", async () => {
  const applicant = (id, status, extra = {}) => ({ app_id: id, status, documents: [], audit_details: {}, ...extra });
  const pool = { async query(sql) {
    assert.match(sql.trim(), /^SELECT/);
    return { rows: sql.includes("FROM orphan_documents") ? [{ id: "orphan-id", filename: "unmatched.pdf", minio_key: "incoming/unmatched.pdf", sha256: "abc" }]
      : [applicant("APP_A", "ERROR", { run_status: "AI_VALIDATION_FAILED", run_validation: { failed_sections: { evidence: ["Citation mismatch"] } }, has_dossier: true }),
        applicant("APP_B", "ERROR", { audit_details: { missing_documents: ["transcript"] } })] };
  } };
  const store = load("../src/lib/it-exception-store.ts", { "@/lib/it-exceptions.mjs": { isItActionable } });
  const exceptions = await store.detectItExceptions(pool);
  assert.deepEqual(exceptions.map(item => item.id), ["applicant-APP_A-summarizer", "orphan-orphan-id"]);
  assert.deepEqual(exceptions[0].findings, ["Evidence: Citation mismatch"]);
  assert.equal(exceptions[0].hasDossier, true);
  assert.equal(exceptions[1].applicantId, null);
  assert.deepEqual(exceptions[1].affectedDocuments, ["unmatched.pdf"]);
});

test("IT actions require a scoped command, note, actor and explicit retry confirmation", async () => {
  const guards=load("../src/lib/it-actions.ts");
  const route=load("../src/app/api/exceptions/[id]/route.ts",{
    "next/server":{NextResponse:Response},"@/lib/it-actions":guards,
    "@/lib/dossier":{pool:{connect(){assert.fail("Invalid requests reached storage");}}},
    "@/lib/it-exception-store":{},
  });
  for(const value of [null,{}, {action:"RESOLVE"}, {action:"REQUEST_RETRY",confirmed:false}]) {
    const response=await route.PUT(new Request("http://localhost",{method:"PUT",body:JSON.stringify(value)}),{params:Promise.resolve({id:"APP_A"})});
    assert.equal(response.status,400);
  }
});

test("IT action form distinguishes queued work, source matching, and verified closure",()=>{
  const current=record("APP_A",{fingerprint:"a".repeat(64),revision:0,retryAllowed:true,workerAvailable:false,
    retryJob:{id:"job",state:"QUEUED"},actions:[{action:"NOTE",actor:"IT demo",note:"Investigated <source>",createdAt:"2026-11-01T00:00:00Z"}]});
  const html=panel("../src/components/ItCaseActions.tsx",["","","","",false,false,""],{record:current,onRefresh(){}}).html();
  for(const text of ["Claim investigation","Assign follow-up owner","waiting for a worker","not a successful retry","Investigated &lt;source&gt;","receiving system confirms a correction"])assert.ok(html.includes(text));
  assert.match(html,/<option value="REQUEST_RETRY" disabled=""/);
  const orphan=panel("../src/components/ItCaseActions.tsx",["","","","",false,false,""],{record:record("orphan",{source:"ORPHAN_INTAKE"}),onRefresh(){}}).html();
  assert.match(orphan,/does not attach a file to an applicant/);
});

test("actual IT actions save ownership, notes, retries, replay and verified outcomes atomically",{skip:!process.env.POSTGRES_DB},async t=>{
  const {Client}=require("pg");const {randomUUID}=require("node:crypto");
  const client=new Client({host:process.env.POSTGRES_HOST,port:Number(process.env.POSTGRES_PORT),database:process.env.POSTGRES_DB,user:process.env.POSTGRES_USER,password:process.env.POSTGRES_PASSWORD});
  await client.connect();const schema="it_ui_test_"+randomUUID().replaceAll("-","");
  try {
    await client.query(`CREATE SCHEMA ${schema}`);await client.query(`SET search_path=${schema},public`);
    await client.query(`CREATE TABLE applicants(app_id varchar(64) PRIMARY KEY,first_name text,last_name text,intended_major text,status text,
      officer_recommendation text,final_decision text,documents jsonb DEFAULT '[]',updated_at timestamptz DEFAULT now(),superscored_sat_score integer)`);
    await client.query("INSERT INTO applicants(app_id,status) VALUES('APP_050','AI_VALIDATION_FAILED')");
    await client.query("CREATE TABLE policy_chunks(policy_id text,content text)");
    await client.query(`CREATE TABLE dossier_generation_runs(id bigserial PRIMARY KEY,app_id text,run_status text,validation jsonb,created_at timestamptz DEFAULT now())`);
    await client.query("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES('APP_050','AI_VALIDATION_FAILED','{\"passed\":false,\"failed_sections\":{\"academic\":[\"Unsupported citation\"]}}')");
    await client.query("CREATE TABLE audit_logs(id text PRIMARY KEY,applicant_id text,action text,actor text,details jsonb,created_at timestamptz DEFAULT now())");
    await client.query("CREATE TABLE summary_audit_log(app_id text,event text,details jsonb)");
    await client.query("CREATE TABLE orphan_documents(id text,filename text,minio_key text,detected_app_id text,sha256 text,ingested_at timestamptz DEFAULT now())");
    await client.query("CREATE TABLE document_records(id text,applicant_id text,filename text,minio_object_key text,sha256_checksum text)");
    await client.query(`CREATE TABLE applicant_dossier(app_id varchar(64) PRIMARY KEY,applicant_demographics jsonb,academic_profile jsonb,engagement_profile jsonb,recommendation_profile jsonb,supplemental_essay_profile jsonb,strengths jsonb,review_notes jsonb,policy_assessment jsonb,holistic_assessment text,evidence_map jsonb,generated_at timestamptz,updated_at timestamptz)`);
    for(const name of ["20261031_durable_dossier_review.sql","20261101_integrated_exception_review.sql","20261101_it_exception_actions.sql","20261101_it_exception_actions.sql"])
      await client.query(readFileSync(new URL(`../../storage/migrations/${name}`,import.meta.url),"utf8"));
    const pool={query:(...args)=>client.query(...args),connect:async()=>({query:(...args)=>client.query(...args),release(){}})};
    const store=load("../src/lib/it-exception-store.ts",{"@/lib/it-exceptions.mjs":{isItActionable}});
    const guards=load("../src/lib/it-actions.ts");
    const route=load("../src/app/api/exceptions/[id]/route.ts",{"next/server":{NextResponse:Response},"@/lib/dossier":{pool},"@/lib/it-actions":guards,"@/lib/it-exception-store":store});
    const ctx=id=>({params:Promise.resolve({id})});
    const send=(id,value)=>route.PUT(new Request("http://localhost",{method:"PUT",body:JSON.stringify(value)}),ctx(id));
    let incident=(await store.listItCases(pool))[0];
    assert.equal(incident.caseState,"OPEN");assert.equal(incident.workerAvailable,false);
    const command=(r,action,extra={})=>({commandId:randomUUID(),fingerprint:r.fingerprint,revision:r.revision,actor:"IT demo",note:"Investigated the service and checked the saved evidence",confirmed:true,action,...extra});
    const claim=command(incident,"CLAIM");
    const claimResponse=await send(incident.id,claim);assert.equal(claimResponse.status,200);
    const claimed=await claimResponse.json();const caseKey=`case-${claimed.caseId}`;
    assert.equal((await send(incident.id,claim)).status,200);
    assert.equal((await send(incident.id,{...claim,note:"Conflicting reuse"})).status,409);
    incident=await store.getItCase(pool,caseKey);
    assert.equal(incident.owner,"IT demo");assert.equal(incident.fingerprint,claim.fingerprint);
    assert.equal(incident.actions.length,1);assert.equal(incident.caseState,"IN_PROGRESS");
    assert.equal((await send(caseKey,command(incident,"NOTE",{revision:0}))).status,409);
    await client.query("ALTER TABLE audit_logs ADD CONSTRAINT fail_it_audit CHECK(false) NOT VALID");
    assert.equal((await send(caseKey,command(incident,"NOTE"))).status,503);
    assert.equal((await store.getItCase(pool,caseKey)).revision,incident.revision);
    await client.query("ALTER TABLE audit_logs DROP CONSTRAINT fail_it_audit");
    assert.equal((await send(caseKey,command(incident,"VERIFY_RESOLVED"))).status,409);
    assert.equal((await send(caseKey,command(incident,"REQUEST_RETRY"))).status,409);
    await client.query("INSERT INTO it_retry_workers(id) VALUES($1)",[randomUUID()]);
    incident=await store.getItCase(pool,caseKey);
    const retry=command(incident,"REQUEST_RETRY");
    assert.equal((await send(caseKey,{...retry,confirmed:false})).status,400);
    const queued=await send(caseKey,retry);assert.equal(queued.status,200);
    assert.equal((await (await send(caseKey,retry)).json()).replayed,true);
    incident=await store.getItCase(pool,caseKey);
    assert.equal(incident.retryJob.state,"QUEUED");assert.equal(incident.caseState,"WAITING");
    assert.equal((await send(caseKey,command(incident,"REQUEST_RETRY"))).status,409);
    assert.equal((await send(caseKey,command(incident,"VERIFY_RESOLVED"))).status,409);
    await client.query("UPDATE it_retry_jobs SET state='NEEDS_RECHECK'");
    assert.equal((await send(caseKey,command(incident,"VERIFY_RESOLVED"))).status,200);
    incident=await store.getItCase(pool,caseKey);
    assert.equal(incident.caseState,"IN_PROGRESS");assert.equal(incident.retryJob.state,"FAILED");
    // A real validated receiver effect is required before the case can close.
    await client.query("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES('APP_050','REVIEW_PENDING','{\"passed\":true}')");
    const candidate={app_id:"APP_050",applicant_demographics:{},academic_profile:{},engagement_profile:{},recommendation_profile:{},supplemental_essay_profile:{},strengths:[],review_notes:[],policy_assessment:[],holistic_assessment:"Factual advisory summary",evidence_map:[]};
    await client.query("SELECT route_dossier_candidate('APP_050',2,$1,checkpoint_input_snapshot('APP_050'),'v1',now()+interval '1 day')",[candidate]);
    assert.equal((await send(caseKey,command(incident,"VERIFY_RESOLVED"))).status,200);
    incident=await store.getItCase(pool,caseKey);assert.equal(incident.active,false);assert.equal(incident.caseState,"RESOLVED");
    assert.ok(incident.resolutionEvidence.request_id);
    assert.equal((await client.query("SELECT officer_recommendation FROM applicants")).rows[0].officer_recommendation,null);
    // Orphans can be assigned and annotated, but never matched or dismissed by guesswork.
    const orphanId=randomUUID();await client.query("INSERT INTO orphan_documents(id,filename,minio_key,sha256,detected_app_id) VALUES($1,'unmatched.pdf','saved/orphan.pdf',$2,'APP_050')",[orphanId,"b".repeat(64)]);
    let orphan=(await store.listItCases(pool)).find(r=>r.source==="ORPHAN_INTAKE");
    const handoff=await send(orphan.id,command(orphan,"HANDOFF",{owner:"Intake matching team"}));assert.equal(handoff.status,200);
    const orphanCase=`case-${(await handoff.json()).caseId}`;orphan=await store.getItCase(pool,orphanCase);
    assert.equal((await client.query("SELECT applicant_id FROM it_exception_cases WHERE source='ORPHAN_INTAKE'")).rows[0].applicant_id,null);
    assert.equal(orphan.owner,"Intake matching team");assert.equal((await send(orphanCase,command(orphan,"VERIFY_RESOLVED"))).status,409);
    await client.query("INSERT INTO document_records VALUES($1,'APP_050','unmatched.pdf','saved/orphan.pdf',$2)",[randomUUID(),"b".repeat(64)]);
    await client.query("UPDATE applicants SET documents=$1",[JSON.stringify([{filename:"unmatched.pdf",minio_key:"saved/orphan.pdf",sha256:"b".repeat(64),exists:true}])]);
    assert.equal((await send(orphanCase,command(orphan,"VERIFY_RESOLVED"))).status,200);
    const snapshot={};for(const table of ["it_exception_cases","it_retry_jobs","it_exception_actions"])
      snapshot[table]=(await client.query(`SELECT * FROM ${table}`)).rows;
    t.diagnostic("it_receiver_snapshot: "+JSON.stringify(snapshot));
  } finally {
    await client.query("ROLLBACK");await client.query("SET search_path=public");assert.match(schema,/^it_ui_test_[a-f0-9]+$/);
    await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);await client.end();
  }
});
