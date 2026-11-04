import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

// This builder uses the bundled artifact-tool via a workspace-only junction.
const root = process.cwd();
const bundledRequire = createRequire(path.join(root,'tmp','cost_baseline_authoring','package.json'));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(bundledRequire.resolve('@oai/artifact-tool')).href);
const input = path.resolve(process.argv[2]);
const output = path.resolve(root, 'outputs', path.basename(input));
await fs.mkdir(output, {recursive: true});
const read = async name => JSON.parse(await fs.readFile(path.join(input, name), 'utf8'));
const jsonl = async name => (await fs.readFile(path.join(input,name),'utf8')).trim().split(/\r?\n/).filter(Boolean).map(x=>JSON.parse(x));
const [results, summary, quality, initial, final, calls] = await Promise.all([
  read('results.json'), read('summary.json'), read('quality_checks.json'), read('storage_initial.json'), read('storage_final.json'), jsonl('calls.jsonl')]);
const wb = Workbook.create();
const names = ['Summary','Ingestion','Dossiers','Chat','Storage','Resources','Facts','Citations','Human review','Model calls'];
const sheets = Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const navy='#233B59', ink='#243247', pale='#F1F4F8', amber='#FFF2CC';
const letter = i => { let s=''; for(i++;i>0;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s; return s; };
function table(name,title,headers,rows,widths=[]) {
  const s=sheets[name], last=letter(headers.length-1), end=rows.length+4;
  s.showGridLines=false;
  s.getRange(`A1:${last}${Math.max(end,7)}`).format.font={name:'Arial',size:10,color:ink};
  s.getRange('A2').values=[[title]];
  s.getRange('A2').format.font={size:15,bold:true,color:navy};
  s.getRange(`A4:${last}4`).values=[headers];
  s.getRange(`A4:${last}4`).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:34};
  if(rows.length) s.getRange(`A5:${last}${end}`).values=rows.map(r=>r.map(v=>v??null));
  for(let r=5;r<=end;r++)if(r%2===0)s.getRange(`A${r}:${last}${r}`).format.fill=pale;
  if(rows.length) s.getRange(`A5:${last}${end}`).format.rowHeight=22;
  for(let i=0;i<headers.length;i++)s.getRange(`${letter(i)}4:${letter(i)}${Math.max(end,7)}`).format.columnWidth=widths[i]??17;
  s.getRange(`A4:${last}${Math.max(end,7)}`).format.verticalAlignment='center';
  s.freezePanes.freezeRows(4);
  s.freezePanes.freezeColumns(name==='Ingestion'||name==='Storage'?1:2);
  return {s,end};
}
const yes=v=>typeof v==='boolean'?v:null;
const scaled=(v,divisor)=>typeof v==='number'?v/divisor:null;
const rmap=Object.fromEntries(summary.resources_by_stage.map(r=>[r.stage,r]));
const chatReview = await read('chat_review.json');
const reviewByStage=Object.fromEntries(chatReview.requests.map(r=>[r.stage,r]));
const inputChecks=await read('input_score_checks.json');

table('Ingestion','Ingestion batches',[
 'Batch','Applicants','Ready','Awaiting','Incomplete','Gate errors','Upload attempts','Unique uploads','Uploaded bytes','Wall seconds','Failed uploads','Application retries','DB growth bytes','Object growth bytes','SDK retries'],
 results.ingestion.map(r=>[r.batch,r.applicants_processed,r.ready,r.awaiting,r.incomplete,r.gate_errors,r.upload_attempts,r.unique_uploaded_documents,r.successful_upload_bytes,r.wall_seconds,r.upload_failed_attempts,r.application_upload_retry_attempts,r.postgres_growth_bytes,r.minio_growth_bytes,'Unobserved']),
 [18,14,12,12,14,12,16,16,18,16,15,16,18,18,18]);
sheets.Ingestion.getRange('J5:J6').setNumberFormat('0.000');
sheets.Ingestion.getRange('B5:I6').setNumberFormat('#,##0');
sheets.Ingestion.getRange('K5:N6').setNumberFormat('#,##0');
sheets.Ingestion.getRange('A8').values=[['Strict live PostgreSQL and MinIO. Missing materials are expected routing outcomes.']];
sheets.Ingestion.getRange('A9').values=[['Fixtures were upserted into existing storage. Growth is not a new-applicant storage estimate.']];
sheets.Ingestion.getRange('A11:B11').values=[['One-time setup','Wall seconds']];
sheets.Ingestion.getRange('A12:B12').values=[['Policy index rebuild',results.checks.find(r=>r.name==='policy_index')?.wall_seconds??null]];
sheets.Ingestion.getRange('A11:A12').format.columnWidth=28;

table('Dossiers','Dossier generation attempts',[
 'Run','Applicant','Repeat','Status','Wall seconds','Rendered pages','VLM calls','Embedding calls','Input tokens','Output tokens','Section retries','Rejected attempts','Auto validation','GPU kWh sampled','Peak VRAM MiB','Cohort','Successful seconds'],
 results.agent.map(r=>[r.stage,r.app_id,r.repetition,r.status,r.wall_seconds,r.unique_pdf_pages,r.llm_vlm_calls,r.embedding_calls,r.known_input_tokens,r.known_output_tokens,r.section_retry_attempts,r.validation_rejected_attempts,yes(r.validation_passed),rmap[r.stage]?.sampled_gpu_kwh,rmap[r.stage]?.gpu_vram_used_mib_max,r.app_id==='APP_013'?'Historical failure probe':'Routine/repeat',null]),
 [30,15,10,26,16,14,12,15,16,16,15,17,16,18,18,25,20]);
for(let row=5;row<=results.agent.length+4;row++)sheets.Dossiers.getRange(`Q${row}`).formulas=[[`=IF(D${row}="DOSSIER_READY",E${row},"")`]];
sheets.Dossiers.getRange(`E5:E${results.agent.length+4}`).setNumberFormat('0.0');
sheets.Dossiers.getRange(`F5:L${results.agent.length+4}`).setNumberFormat('#,##0');
sheets.Dossiers.getRange(`N5:N${results.agent.length+4}`).setNumberFormat('0.00000');
sheets.Dossiers.getRange(`D5:D${results.agent.length+4}`).conditionalFormats.add('containsText',{text:'ERROR',format:{fill:'#FCE4E4',font:{color:'#9C2020'}}});
sheets.Dossiers.getRange(`D5:D${results.agent.length+4}`).conditionalFormats.add('containsText',{text:'FAILED',format:{fill:'#FCE4E4',font:{color:'#9C2020'}}});

table('Chat','Fixed chat question set',[
 'Run','Applicant','Question type','HTTP status','Wall seconds','VLM calls','Input tokens','Output tokens','Model seconds','Transport failure','Question','Answer excerpt','Assistant assessment'],
 results.chat.map(r=>[r.stage,r.app_id,r.question_type,r.http_status,r.wall_seconds,r.llm_vlm_calls,r.known_input_tokens,r.known_output_tokens,r.model_reported_seconds,r.http_status!==200?1:0,r.question,(r.response?.reply??r.exception??r.response?.error??'').slice(0,320),reviewByStage[r.stage]?.assessment]),
 [38,15,23,14,16,12,16,16,16,18,70,100,52]);
sheets.Chat.getRange(`E5:E${results.chat.length+4}`).setNumberFormat('0.00');
sheets.Chat.getRange(`G5:H${results.chat.length+4}`).setNumberFormat('#,##0');
sheets.Chat.getRange(`I5:I${results.chat.length+4}`).setNumberFormat('0.000');
sheets.Chat.getRange(`K5:L${results.chat.length+4}`).format.wrapText=true;
sheets.Chat.getRange(`K5:L${results.chat.length+4}`).format.autofitRows();

table('Storage','Storage snapshots',[
 'Snapshot','PostgreSQL bytes','Current objects','Current object bytes','Scope'],
 [['Before',initial.postgres_database_bytes,initial.minio_current_objects,initial.minio_current_object_bytes,'Existing test data'],
 ['After',final.postgres_database_bytes,final.minio_current_objects,final.minio_current_object_bytes,'Current logical objects only']],
 [18,22,20,25,45]);
sheets.Storage.getRange('A9:D9').values=[['Final database table','Records','Bytes including indexes','Measurement']];
sheets.Storage.getRange('A9:D9').format={fill:navy,font:{bold:true,color:'#FFFFFF'},rowHeight:28};
const tableRows=final.tables.map(t=>[t.table,t.records,t.bytes_including_indexes,'PostgreSQL relation size']);
if(tableRows.length)sheets.Storage.getRange(`A10:D${9+tableRows.length}`).values=tableRows;
sheets.Storage.getRange('B5:D6').setNumberFormat('#,##0');
sheets.Storage.getRange(`B10:C${9+tableRows.length}`).setNumberFormat('#,##0');
sheets.Storage.getRange(`A10:A${9+tableRows.length}`).format.columnWidth=30;

table('Resources','Resource measurements by workload stage',[
 'Stage','Samples','Mean host CPU %','Peak host CPU %','Mean host RAM GiB','Peak host RAM GiB','Mean GPU %','Peak GPU %','Mean VRAM GiB','Peak VRAM GiB','Mean GPU watts','Peak GPU watts','GPU kWh sampled','Energy coverage sec'],
 summary.resources_by_stage.map(r=>[r.stage,r.samples,r.host_cpu_percent_mean,r.host_cpu_percent_max,scaled(r.host_ram_used_bytes_mean,2**30),scaled(r.host_ram_used_bytes_max,2**30),r.gpu_util_percent_mean,r.gpu_util_percent_max,scaled(r.gpu_vram_used_mib_mean,1024),scaled(r.gpu_vram_used_mib_max,1024),r.gpu_power_watts_mean,r.gpu_power_watts_max,r.sampled_gpu_kwh,r.gpu_energy_sampled_seconds]),
 [40,12,18,18,20,20,16,16,18,18,18,18,20,20]);
sheets.Resources.getRange(`C5:L${summary.resources_by_stage.length+4}`).setNumberFormat('0.0');
sheets.Resources.getRange(`M5:M${summary.resources_by_stage.length+4}`).setNumberFormat('0.00000');

const facts=table('Facts','Academic fixture checks',[
 'Run','Applicant','Field','CSV expected','Dossier value','Matches fixture','Scope'],
 quality.facts.map(r=>[r.stage,r.app_id,r.field,r.fixture_csv_expected,r.dossier_value,yes(r.matches_fixture),r.scope]),
 [30,15,23,18,18,18,70]);
const privacyStart=facts.end+4;
sheets.Facts.getRange(`A${privacyStart}:D${privacyStart}`).values=[['Run','Applicant','Restricted fixture field','Exact matches in output']];
sheets.Facts.getRange(`A${privacyStart}:D${privacyStart}`).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34};
if(quality.privacy.length)sheets.Facts.getRange(`A${privacyStart+1}:D${privacyStart+quality.privacy.length}`).values=quality.privacy.map(r=>[r.stage,r.app_id,r.restricted_field,r.exact_value_matches_in_output]);
sheets.Facts.getRange(`A${privacyStart+1}:D${privacyStart+quality.privacy.length}`).format.font={name:'Arial',size:10};
sheets.Facts.getRange(`A${privacyStart+quality.privacy.length+2}`).values=[['Exact matches are review flags. Complete matching paths are preserved in the raw privacy results.']];
const courseStart=privacyStart+quality.privacy.length+5;
sheets.Facts.getRange(`A${courseStart}:F${courseStart}`).values=[['Run','Applicant','Fixture AP courses','Extracted courses','Fixture courses matched','Missing fixture courses']];
sheets.Facts.getRange(`A${courseStart}:F${courseStart}`).format={fill:navy,font:{bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:34};
if(quality.course_coverage.length)sheets.Facts.getRange(`A${courseStart+1}:F${courseStart+quality.course_coverage.length}`).values=quality.course_coverage.map(r=>[r.stage,r.app_id,r.fixture_ap_courses,r.extracted_ap_courses,r.fixture_courses_matched,r.missing_fixture_courses]);
const inputStart=courseStart+quality.course_coverage.length+4;
sheets.Facts.getRange(`A${inputStart}:F${inputStart}`).values=[['Applicant','Test','Fixture score','Minimum','Maximum','Range check']];
sheets.Facts.getRange(`A${inputStart}:F${inputStart}`).format={fill:navy,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
sheets.Facts.getRange(`A${inputStart+1}:F${inputStart+inputChecks.length}`).values=inputChecks.map(r=>[r.app_id,r.field.includes('SAT')?'SAT':'ACT',r.fixture_value.trim()?Number(r.fixture_value):null,r.minimum,r.maximum,r.status==='valid'?'Valid':r.status==='missing_optional_score'?'Missing optional':'Invalid']);
sheets.Facts.getRange(`A${inputStart+1}:F${inputStart+inputChecks.length}`).format.font={name:'Arial',size:10};
sheets.Facts.getRange(`F${inputStart+1}:F${inputStart+inputChecks.length}`).conditionalFormats.add('containsText',{text:'Invalid',format:{fill:'#FCE4E4',font:{color:'#9C2020',bold:true}}});

table('Citations','Independent quotation checks',[
 'Run','Applicant','Section','Document','Page','Quotation','Agent verification','Independent text check'],
 quality.citations.map(r=>[r.stage,r.app_id,r.section,r.document,r.page,r.quote,r.agent_verification,r.independent_text_check]),
 [30,15,25,35,10,100,32,50]);
sheets.Citations.getRange(`F5:F${quality.citations.length+4}`).format.wrapText=true;
sheets.Citations.getRange(`F5:F${quality.citations.length+4}`).format.autofitRows();

table('Human review','Human review measurements to collect',[
 'Run','Applicant','Reviewer','Mode','Review minutes','Facts checked','Factual errors','Citations checked','Citation errors','Correction minutes','Notes'],
 quality.human_review.map(r=>[r.stage,r.app_id,r.human_reviewer,r.review_mode_manual_or_assisted,r.human_review_minutes,r.facts_checked,r.factual_errors,r.citations_checked,r.citation_errors,r.correction_minutes,r.notes]),
 [30,15,24,18,18,16,16,18,16,20,65]);
sheets['Human review'].getRange(`C5:K${quality.human_review.length+4}`).format.fill=amber;
sheets['Human review'].getRange(`D5:D${quality.human_review.length+4}`).dataValidation={rule:{type:'list',values:['manual','assisted','failure_triage']}};
sheets['Human review'].getRange(`A${quality.human_review.length+7}`).values=[['Blank cells are unmeasured. Use a stopwatch and record inspection and correction time separately.']];

const ns=v=>typeof v==='number'?v/1e9:null;
table('Model calls','Observed Ollama calls',[
 'Stage','Applicant','Section','Endpoint','Model','Input tokens','Output tokens','Model seconds','Load seconds','Prompt seconds','Decode seconds','HTTP wall seconds','Image submissions','HTTP status','Stream completed','Stop reason'],
 calls.map(r=>[r.stage,r.app_id,r.section,r.endpoint,r.requested_model,r.prompt_eval_count,r.eval_count,ns(r.total_duration),ns(r.load_duration),ns(r.prompt_eval_duration),ns(r.eval_duration),r.wall_seconds,r.images,r.http_status,r.stream_completed,r.done_reason]),
 [38,15,20,18,28,16,16,16,16,16,16,20,18,14,18,20]);
sheets['Model calls'].getRange(`H5:L${calls.length+4}`).setNumberFormat('0.000');
sheets['Model calls'].getRange(`F5:G${calls.length+4}`).setNumberFormat('#,##0');

const s=sheets.Summary;
s.showGridLines=false;s.tabColor=navy;
s.getRange('A1:F49').format.font={name:'Arial',size:10,color:ink};
s.getRange('A2').values=[['Admissions system baseline']];s.getRange('A2').format.font={size:16,bold:true,color:navy};
s.getRange('A3').values=[['Synthetic fixtures. October 21, 2026. Sequential local inference.']];
s.getRange('A5:D5').values=[['Metric','Measured result','Unit','Coverage']];
s.getRange('A5:D5').format={fill:navy,font:{bold:true,color:'#FFFFFF'},rowHeight:28};
const endAgent=results.agent.length+4,endChat=results.chat.length+4,endResources=summary.resources_by_stage.length+4;
const entries=[
 ['Ingestion applicants',"=SUM('Ingestion'!B5:B6)",'applicants','Both complete fixture batches'],
 ['Documents uploaded',"=SUM('Ingestion'!H5:H6)",'documents','Confirmed uploads; two batches'],
 ['Upload byte volume',"=SUM('Ingestion'!I5:I6)/1000000",'MB','Decimal MB; attempts differ from stored bytes'],
 ['Ingestion execution time',"=SUM('Ingestion'!J5:J6)",'seconds','Strict PostgreSQL and MinIO'],
 ['Dossier attempts',results.agent.length,'runs','Includes repeat and selected failure probe'],
 ['Successful dossier attempts',`=COUNTIFS('Dossiers'!D5:D${endAgent},"DOSSIER_READY")`,'runs','Automated validation; quality checked separately'],
 ['Routine successful attempts',summary.routine_successful_runs,'runs',`${summary.routine_runs} routine/repeat attempts; excludes selected failure probe`],
 ['Successful unique applicants',summary.successful_unique_applicants,'applicants','Repeated APP_012 counts once'],
 ['Successful run mean duration',`=IF(COUNT('Dossiers'!Q5:Q${endAgent})=0,"n.a.",AVERAGE('Dossiers'!Q5:Q${endAgent}))`,'seconds','Successful attempts only'],
 ['Successful run median duration',`=IF(COUNT('Dossiers'!Q5:Q${endAgent})=0,"n.a.",MEDIAN('Dossiers'!Q5:Q${endAgent}))`,'seconds','Small selected sample'],
 ['Wall time per successful dossier',`=IF(B11=0,"n.a.",SUM('Dossiers'!E5:E${endAgent})/B11)`,'seconds','Includes time spent on failed attempts'],
 ['Dossier VLM calls',`=SUM('Dossiers'!G5:G${endAgent})`,'calls','All attempts'],
 ['Dossier input tokens',`=SUM('Dossiers'!I5:I${endAgent})`,'tokens','Known usage; completeness in JSON summary'],
 ['Dossier output tokens',`=SUM('Dossiers'!J5:J${endAgent})`,'tokens','Known usage; includes rejected outputs'],
 ['Section retry attempts',`=SUM('Dossiers'!K5:K${endAgent})`,'attempts','Section retries; early failures may lack section data'],
 ['Chat requests',results.chat.length,'requests','Fixed questions plus three guardrail probes'],
 ['Chat HTTP failures',`=SUM('Chat'!J5:J${endChat})`,'requests','Expected invalid-request smoke tests are separate'],
 ['Chat mean response time',`=AVERAGE('Chat'!E5:E${endChat})`,'seconds','Full request; API response is not streamed'],
 ['Chat median response time',`=MEDIAN('Chat'!E5:E${endChat})`,'seconds','Small selected sample'],
 ['Chat mean input tokens',`=IF(COUNT('Chat'!G5:G${endChat})=COUNTA('Chat'!A5:A${endChat}),AVERAGE('Chat'!G5:G${endChat}),"n.a.")`,'tokens/request','All benchmark chat requests; unavailable if any token count is missing'],
 ['Chat mean output tokens',`=IF(COUNT('Chat'!H5:H${endChat})=COUNTA('Chat'!A5:A${endChat}),AVERAGE('Chat'!H5:H${endChat}),"n.a.")`,'tokens/request','All benchmark chat requests; unavailable if any token count is missing'],
 ['Final PostgreSQL size',"='Storage'!B6/1000000",'MB','Database size; table sizes on Storage'],
 ['Final MinIO logical size',"='Storage'!D6/1000000",'MB','Current objects only; excludes backups/overhead'],
 ['Final MinIO current objects',"='Storage'!C6",'objects','Includes objects outside this experiment'],
 ['Source object integrity',`${summary.source_objects_matching}/${summary.source_objects_checked}`,'matching','Downloaded bytes compared with fixture bytes'],
 ['Expected routing checks',`${summary.fixture_routing_matches}/${summary.fixture_routing_checks}`,'matching','Explicit fixture status expectations'],
 ['Academic fixture checks',`${summary.academic_fixture_fields_matching}/${summary.academic_fixture_fields_checked}`,'matching','Four numeric fields; not full factual accuracy'],
 ['Peak sampled GPU VRAM',`=MAX('Resources'!J5:J${endResources})`,'GiB','Whole GPU; sampled every approximately 2 seconds'],
 ['Human reviewer time','Unmeasured','minutes','Editable measurement form on Human review'],
 ['Whole-system electricity','Unmeasured','kWh','GPU board power is recorded separately'],
 ['Active benchmark workload',`=SUM('Ingestion'!J5:J6,'Dossiers'!E5:E${endAgent},'Chat'!E5:E${endChat})+'Ingestion'!B12`,'seconds','Ingestion + index + selected dossiers + chat'],
];
entries.forEach((r,i)=>{const n=i+6;s.getRange(`A${n}:D${n}`).values=[[r[0],typeof r[1]==='string'&&r[1].startsWith('=')?null:r[1],r[2],r[3]]];if(typeof r[1]==='string'&&r[1].startsWith('='))s.getRange(`B${n}`).formulas=[[r[1]]];if(n%2===0)s.getRange(`A${n}:D${n}`).format.fill=pale;});
s.getRange('A6:D36').format.rowHeight=23;
s.getRange('A5:A36').format.columnWidth=36;s.getRange('B5:B36').format.columnWidth=23;s.getRange('C5:C36').format.columnWidth=20;s.getRange('D5:D36').format.columnWidth=65;
s.getRange('B6:B36').setNumberFormat('#,##0.0');
entries.forEach((r,i)=>{if(['applicants','documents','runs','calls','tokens','attempts','requests','objects'].includes(r[2]))s.getRange(`B${i+6}`).setNumberFormat('#,##0');});
s.getRange('B8').setNumberFormat('0.000');
s.getRange('B23:B24').setNumberFormat('0.00');
s.getRange('B27:B28').setNumberFormat('0.000');
s.getRange('A39').values=[['Interpretation']];s.getRange('A39').format.font={bold:true,color:navy};
s.getRange('A40').values=[['Model use can be mixed CPU/GPU. Processor split and quantization are preserved in raw evidence.']];
s.getRange('A41').values=[['This selected sample does not establish a production failure rate or a reliable p95.']];
s.getRange('A42').values=[['Rates for electricity, hardware allocation, hosting, retention, and labor have not been assumed.']];
s.getRange('A43').values=[['Automated validation is separate from factual accuracy, privacy, and chat guardrail results.']];
s.getRange('A44').values=[['Sources: live benchmark results, Ollama responses, storage queries, resource samples, and fixture checks.']];
s.getRange('A45').values=[['Ordinary Python and contract test failures are preserved in the accompanying test report.']];
s.getRange('A46').values=[['Input score check: SAT 31 is stored in APP_014 source data. It is outside the valid SAT range.']];
s.getRange('A47').values=[['Chat: GPA answers are supported; policy answers need correction; the client system-role boundary failed.']];
// Check the failure-inclusive unit-time formula points to successful attempts.
if(entries[5][0]!=='Successful dossier attempts')throw new Error('Summary denominator moved');
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Summary!A5:D20',include:'values,formulas',tableMaxRows:16,tableMaxCols:4,maxChars:5000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},summary:'Formula error scan'})).ndjson);
for(const name of (process.argv.includes('--updated-previews')?['Summary','Ingestion','Dossiers','Chat','Storage','Facts','Model calls']:names)){
 const range=name==='Summary'?'A1:D24':name==='Chat'?'A1:J10':name==='Model calls'?'A1:L10':name==='Resources'?'A1:N10':name==='Human review'?'A1:K10':name==='Citations'?'A1:H9':name==='Facts'?'A1:G12':name==='Storage'?'A1:E18':name==='Ingestion'?'A1:O9':'A1:P12';
 const preview=await wb.render({sheetName:name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(output,name.replaceAll(' ','_')+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
for(const [name,sheetName,range] of [['Facts_privacy','Facts',`A${privacyStart}:D${privacyStart+9}`],['Facts_scores','Facts',`A${inputStart+21}:F${inputStart+31}`],['Summary_notes','Summary','A25:D47']]){
 const preview=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(path.join(output,name+'.png'),new Uint8Array(await preview.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(path.join(output,'cost_baseline.xlsx'));
await fs.writeFile(path.join(output,'workbook_check.json'),JSON.stringify({summary:await wb.inspect({kind:'table',range:'Summary!A5:D36',include:'values,formulas',tableMaxRows:32,tableMaxCols:4,maxChars:15000})},null,2));
console.log('Saved '+path.join(output,'cost_baseline.xlsx'));
