"""Reproduce the Milestone 2 intake review without using live storage or a model.
Run from the repository root with the dependencies in requirements.txt installed.
All generated fixtures and reports go to tmp/m2_evaluation. Production code is unchanged.
"""
from pathlib import Path
import os, sys, json, csv, shutil, copy, logging, subprocess, importlib.metadata
from datetime import datetime, timezone
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['MINIO_ENDPOINT']='127.0.0.1:65534'
from ingestion.batch_ingest import BatchIngestor
from validation.manifest_gate import ManifestValidationGate
from ingestion.pipeline import BatchIngestionPipeline
from storage.storage_manager import StorageManager
from gateway.client import ModelGateway
from gateway.models import InferenceRequest, DocumentItem
from run_ingestion_check import run_pipeline
import yaml
WORK=ROOT/'tmp/m2_evaluation'
WORK.mkdir(parents=True,exist_ok=True)
logging.basicConfig(filename=WORK/'execution.log',level=logging.INFO,force=True,format='%(asctime)s %(levelname)s %(name)s %(message)s')

def isolated_storage():
    with patch.object(StorageManager,'_init_minio_connection'):
        return StorageManager(database_url='sqlite:///:memory:')

def intake(path,config=None):
    st=isolated_storage()
    apps=BatchIngestor(config_path=config,storage_manager=st).ingest_batch(path)
    gate=ManifestValidationGate(config_path=config)
    return st,apps,gate.evaluate_batch(apps.applications)

st,apps,batch=intake(ROOT/'batch_01')
results={'reviewed_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    'evaluated_at_utc':datetime.now(timezone.utc).isoformat(),'storage_mode':'SQLite in memory; MinIO disabled',
    'actual_model_calls':0,'python':sys.version.split()[0],
    'versions':{m:importlib.metadata.version(m) for m in ('SQLAlchemy','pydantic','pytest','PyYAML','requests','minio')},
    'batch':batch.to_dict(),'documents':sum(len(a.documents) for a in apps),
    'comparison':[],'probes':{}}
# Independent expected routes are based on intentionally controlled fixture edits.
cases=[('complete','READY_FOR_REVIEW',None),('missing_transcript','INCOMPLETE','transcript.pdf'),
       ('optional_test_absent','READY_FOR_REVIEW','standardized_test_score.pdf'),
       ('bad_pdf_header','ERROR','bad_header'),('one_lor','INCOMPLETE','recommendation_letter_2.pdf')]
for name,expected,change in cases:
    base=WORK/name
    dest=base/'APP_001'
    dest.mkdir(parents=True,exist_ok=True)
    # Recreate the fixture deterministically without deleting any directories.
    for src in (ROOT/'batch_01/APP_001').glob('*.pdf'): shutil.copy2(src,dest/src.name)
    with (ROOT/'batch_01/applicant_data.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f); row=next(r for r in reader if r['App_ID']=='APP_001'); fields=reader.fieldnames
    with (base/'applicant_data.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerow(row)
    if change=='bad_header':
        p=dest/'transcript.pdf'; content=p.read_bytes(); p.write_bytes(b'NOTPD'+content[5:])
    elif change: (dest/change).unlink()
    _,fixture,routed=intake(base)
    actual=routed.routed_applicants[0]
    # Credible simpler alternative: required fields and recognized filenames only.
    ing=BatchIngestor(storage_manager=isolated_storage())
    present=[ing.classify_document(p.name) for p in dest.iterdir() if p.is_file()]
    needed={'application_form','transcript','personal_statement'}
    baseline='READY_FOR_REVIEW' if needed.issubset(present) and sum('recommendation_letter' in t for t in present)>=2 else 'INCOMPLETE'
    results['comparison'].append({'case':name,'expected':expected,'filename_checklist':baseline,
        'current_gate':actual.status.value,'baseline_correct':baseline==expected,'current_correct':actual.status.value==expected,
        'missing_documents':actual.missing_documents,'errors':actual.errors})
results['comparison_scores']={k:sum(r[k] for r in results['comparison']) for k in ('baseline_correct','current_correct')}
# Re-run CLI orchestration using isolated storage; preserve the tracked team's outputs.
with patch.object(StorageManager,'_init_minio_connection'):
    cli=run_pipeline(input_dir='batch_01',report_file=str(WORK/'ingestion_report.txt'),
       affected_ids_file=str(WORK/'affected_ids.json'),storage_manager=isolated_storage())
results['probes']['cli_matches_batch']=cli.to_dict()['affected_ids']==batch.affected_ids
pipe=BatchIngestionPipeline(source_dir=ROOT/'batch_01')
manifest=pipe.assemble_manifest(ROOT/'batch_01/APP_001','APP_001')
legacy=pipe.validator.validate(manifest)
results['probes']['scaffold_manifest']=legacy.model_dump(mode='json')
results['probes']['scaffold_batch']=pipe.run_batch()
results['probes']['default_source_exists']=BatchIngestionPipeline().source_dir.exists()
# Simulated outage and malformed model response: these are control probes, not AI evaluation.
gateway=ModelGateway()
request=InferenceRequest(applicant_id='APP_001',documents=[
    DocumentItem(document_type='transcript',filename='transcript.pdf',content='Transcript marker'),
    DocumentItem(document_type='personal_statement',filename='personal_statement.pdf',content='PRIVATE_ESSAY_MARKER')])
with patch('gateway.client.requests.post',side_effect=ConnectionError('Controlled outage')):
    fallback=gateway.evaluate_applicant(request)
results['probes']['gateway_outage']={'status':fallback.status,'model_name':fallback.model_name,
    'bypassed_documents':fallback.bypassed_documents}
class BadResponse:
    status_code=200
    def json(self): return {'message':{'content':'This is not valid JSON.'}}
with patch('gateway.client.requests.post',return_value=BadResponse()) as post:
    malformed=gateway.evaluate_applicant(request)
    prompt=post.call_args.kwargs['json']['messages'][-1]['content']
results['probes']['malformed_model_json']={'status':malformed.status,'evaluation_summary':malformed.evaluation_summary,
    'essay_marker_in_prompt':'PRIVATE_ESSAY_MARKER' in prompt,
    'policy_ids':[p.policy_id for p in malformed.policy_citations]}
# Demonstrate that the active gate does not apply its configured aggregate packet limit.
cfg=yaml.safe_load((ROOT/'config/policies.yaml').read_text())
cfg['file_constraints']['max_packet_size_bytes']=1024
cfg_path=WORK/'small_packet_limit.yaml'; cfg_path.write_text(yaml.safe_dump(cfg),encoding='utf-8')
_,limited,limited_result=intake(WORK/'complete',cfg_path)
results['probes']['aggregate_packet_limit']={'configured_limit_bytes':1024,
    'actual_packet_bytes':sum(d.file_size_bytes for d in limited[0].documents),
    'status':limited_result.routed_applicants[0].status.value}
results['probes']['ap_course_mapping']=[{'app_id':a.applicant_id,'source_total_aps':a.metadata.get('Total_APs'),
    'source_course_count':len([x for x in (a.metadata.get('AP_Courses') or '').split(',') if x.strip()]),
    'stored_ap_test_scores_count':len(a.ap_test_scores),'stored_ap_test_scores_are_course_names':a.ap_test_scores[:2]} for a in apps]
# Check a fresh installation with DATABASE_URL unset. This invokes --help only, so no writes run.
env=os.environ.copy(); env.pop('DATABASE_URL',None)
startup=subprocess.run([sys.executable,'-S','run_ingestion_check.py','--help'],env=env,capture_output=True,text=True)
results['probes']['unconfigured_startup']={'returncode':startup.returncode,
    'last_error':startup.stderr.strip().splitlines()[-1] if startup.stderr.strip() else ''}
(WORK/'review_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps({'batch':{k:batch.to_dict()[k] for k in ['total_processed','total_valid','total_incomplete','total_error']},
    'comparison':results['comparison'],'comparison_scores':results['comparison_scores'],
    'probes':{k:v for k,v in results['probes'].items() if k not in ['scaffold_batch','scaffold_manifest','ap_course_mapping']}},indent=2))

