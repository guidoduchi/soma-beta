import {useState} from 'react';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type Ref=Readonly<{kind:string;id:string}>;
type Proposal=Readonly<{proposal_id:string;sheet_kind:'network_elements'|'ip_addresses';row_ordinal:number;
  action:string;state:string;target_network_element_id:string|null;expected_revision:number|null;
  input_fingerprint:string;warning_codes:readonly string[]}>;
type History=Readonly<{items:readonly {kind:'run'|'export';id:string;timestamp_utc:number;state_or_mode:string;filename:string;sha256:string}[];next_cursor:unknown|null}>;
type Run=Readonly<{run_id:string;state:string;revision:number;workbook_version:string;mode:string;
  installation_relation:'same_installation'|'foreign_installation';file_sha256:string;logical_fingerprint:string;
  row_counts:Readonly<{network_elements:number;ip_addresses:number;warnings:number}>;
  proposal_counts:Readonly<{pending:number;accepted:number;rejected:number;superseded:number;ambiguous:number;invalid:number}>;
  proposals:readonly Proposal[];next_cursor:unknown|null}>;
type Detail=Readonly<{proposal:Proposal;impact:Readonly<{creates:readonly Ref[];updates:readonly Ref[];
  relationship_changes:readonly string[];warning_codes:readonly string[];destructive_change:boolean}>;candidate_ids:readonly string[]}>;
const groups:Readonly<Record<string,string>>={create_network_element:'Create',create_related_reference:'Create',
  update_network_element:'Update',update_ip_set:'Update',relationship_change:'Relationship change',
  unchanged:'Unchanged — No change',ambiguous:'Ambiguous',unknown_reference:'Unknown reference',skip_invalid:'Invalid/Skipped'};
const uuid=(value:unknown):value is string=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value);
const count=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>=0;
const hash=(value:unknown)=>typeof value==='string'&&/^[0-9a-f]{64}$/u.test(value);
function warnings(value:readonly string[]) {
  if(!Array.isArray(value)||value.length>32||value.some(item=>typeof item!=='string'||new TextEncoder().encode(item).length>128))throw new Error('Invalid workbook warnings');
  return value.join(', ')||'None';
}
function proposal(row:Proposal) {
  if(!uuid(row.proposal_id)||!['network_elements','ip_addresses'].includes(row.sheet_kind)||!count(row.row_ordinal)||row.row_ordinal<2
    ||!Object.hasOwn(groups,row.action)||!['pending','accepted','rejected','superseded'].includes(row.state)
    ||(row.target_network_element_id!==null&&!uuid(row.target_network_element_id))
    ||(row.expected_revision!==null&&(!count(row.expected_revision)||row.expected_revision<1))||!hash(row.input_fingerprint))throw new Error('Invalid workbook proposal');
  warnings(row.warning_codes);
}
/** Owner continuation is opaque query intent, bounded and checked before enabling Next. */
function continuation(value:unknown,kind:'history'|'run') {
  if(value===null)return;
  if(!value||typeof value!=='object'||Array.isArray(value)||new TextEncoder().encode(JSON.stringify(value)).length>4096)throw new Error('Invalid workbook continuation');
  const cursor=value as Record<string,unknown>;
  const query=kind==='history'?'InfrastructureWorkbookHistoryQuery':'InfrastructureWorkbookRunQuery';
  if(Object.keys(cursor).length!==6||Object.keys(cursor).some(key=>!['version','query_id','sort_registry_id','last_key_tuple','filter_fingerprint','null_order'].includes(key))
    ||cursor.version!==1||cursor.query_id!==query||cursor.sort_registry_id!==query+'_ORDER_V1'||cursor.null_order!=='NOT_APPLICABLE'
    ||!hash(cursor.filter_fingerprint)||!Array.isArray(cursor.last_key_tuple))throw new Error('Invalid workbook cursor identity');
  const key=cursor.last_key_tuple;
  if(kind==='history'?(key.length!==3||!count(key[0])||!['run','export'].includes(key[1])||!uuid(key[2])):
    (key.length!==4||!count(key[0])||key[0]>6||!['network_elements','ip_addresses'].includes(key[1])||!count(key[2])||key[2]<2||!uuid(key[3])))throw new Error('Invalid workbook cursor key');
}
function ProposalDetail({id}:{id:string}) {
  const [candidatePage,setCandidatePage]=useState(0);
  return <section aria-label="Workbook proposal detail"><OwnerProjection<Detail> path={'/api/v1/infrastructure/workbooks/proposals/'+encodeURIComponent(id)} render={value=>{
    proposal(value.proposal);
    const impact=value.impact;
    if(value.proposal.proposal_id!==id||!Array.isArray(value.candidate_ids)||value.candidate_ids.length>500||value.candidate_ids.some(item=>!uuid(item))
      ||new Set(value.candidate_ids).size!==value.candidate_ids.length
      ||!Array.isArray(impact.creates)||impact.creates.length>64||!Array.isArray(impact.updates)||impact.updates.length>64
      ||[...impact.creates,...impact.updates].some(ref=>!uuid(ref.id)||typeof ref.kind!=='string')
      ||!Array.isArray(impact.relationship_changes)||impact.relationship_changes.length>64||impact.relationship_changes.some(item=>typeof item!=='string'||new TextEncoder().encode(item).length>256)
      ||typeof impact.destructive_change!=='boolean')throw new Error('Invalid workbook proposal detail');
    const warningText=warnings(impact.warning_codes);
    const candidates=value.candidate_ids.slice(candidatePage*200,(candidatePage+1)*200);
    return <><h4>Proposal identity: {id}</h4><p>{groups[value.proposal.action]}. Owner state: {value.proposal.state}.</p>
      <p>Target Network Element: {value.proposal.target_network_element_id??'Unresolved'}. Expected revision: {value.proposal.expected_revision??'None'}.</p>
      <p>Destructive change: {impact.destructive_change?'Yes':'No'}. Warnings: {warningText}.</p>
      <h5>Creates</h5><ul>{impact.creates.map(ref=><li key={ref.kind+ref.id}>{ref.kind}: {ref.id}</li>)}</ul>
      <h5>Updates</h5><ul>{impact.updates.map(ref=><li key={ref.kind+ref.id}>{ref.kind}: {ref.id}</li>)}</ul>
      <h5>Relationship changes</h5><ul>{impact.relationship_changes.map((text,index)=><li key={index}>{text}</li>)}</ul>
      <p>Candidate identities: {value.candidate_ids.length}. No candidate is automatically selected.</p>
      <BoundedCollection caption="Workbook candidate identities" rows={candidates.map(identity=>({id:identity,cells:[identity]}))}
        next={(candidatePage+1)*200<value.candidate_ids.length} onNext={()=>setCandidatePage(candidatePage+1)}/></>;
  }}/></section>;
}
function WorkbookRun({id}:{id:string}) {
  const [cursor,setCursor]=useState<unknown|null>(null);const [opened,setOpened]=useState<string|null>(null);
  const path=`/api/v1/infrastructure/workbooks/runs/${encodeURIComponent(id)}?limit=200`+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Workbook run"><OwnerProjection<Run> path={path} render={value=>{
    if(value.run_id!==id||!['validating','staged','reviewed','accepted','rejected','failed'].includes(value.state)
      ||!count(value.revision)||value.revision<1||!['registration_template','discovery','round_trip'].includes(value.mode)
      ||!['same_installation','foreign_installation'].includes(value.installation_relation)||!hash(value.file_sha256)||!hash(value.logical_fingerprint)
      ||['network_elements','ip_addresses','warnings'].some(key=>!count(value.row_counts[key as keyof Run['row_counts']]))
      ||['pending','accepted','rejected','superseded','ambiguous','invalid'].some(key=>!count(value.proposal_counts[key as keyof Run['proposal_counts']]))
      ||!Array.isArray(value.proposals)||value.proposals.length>200)throw new Error('Invalid workbook run');
    value.proposals.forEach(proposal);continuation(value.next_cursor,'run');
    return <><h3>Workbook run: {value.run_id}</h3><p>Owner state: {value.state}. Revision: {value.revision}. Mode: {value.mode}. Workbook version: {value.workbook_version}.</p>
      {value.installation_relation==='foreign_installation'?<p className="warning" role="status">Foreign-installation workbook. Review its scope and identities carefully.</p>:<p>Same-installation workbook.</p>}
      <p>Source SHA-256: {value.file_sha256}. Logical fingerprint: {value.logical_fingerprint}.</p>
      <p>Rows — Network Elements: {value.row_counts.network_elements}; IP addresses: {value.row_counts.ip_addresses}; warnings: {value.row_counts.warnings}.</p>
      <p>Proposals — pending: {value.proposal_counts.pending}; accepted: {value.proposal_counts.accepted}; rejected: {value.proposal_counts.rejected}; superseded: {value.proposal_counts.superseded}; ambiguous: {value.proposal_counts.ambiguous}; invalid: {value.proposal_counts.invalid}.</p>
      {value.proposals.length===0&&<p>No workbook proposals in this page.</p>}
      <BoundedCollection caption="Owner workbook proposals" rows={value.proposals.map(row=>({id:row.proposal_id,cells:[groups[row.action],row.sheet_kind,
        `Row ${row.row_ordinal}`,row.state,row.target_network_element_id??'Unresolved target',warnings(row.warning_codes),
        <button type="button" onClick={()=>setOpened(row.proposal_id)}>Open proposal {row.proposal_id}</button>]}))}
        next={value.next_cursor!==null} onNext={()=>{setOpened(null);setCursor(value.next_cursor);}}/>
      {opened&&<ProposalDetail key={opened} id={opened}/>}</>;
  }}/></section>;
}
export function InfrastructureWorkbookActivity() {
  const [cursor,setCursor]=useState<unknown|null>(null);const [opened,setOpened]=useState<string|null>(null);
  const path='/api/v1/infrastructure/workbooks/history?limit=200'+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Infrastructure workbook activity"><h3>Workbook Activity</h3>
    <p>Installation-wide workbook history. Source workbooks remain read-only and operator-managed during review.</p>
    <OwnerProjection<History> path={path} render={value=>{
      if(!Array.isArray(value.items)||value.items.length>200||value.items.some(item=>!['run','export'].includes(item.kind)||!uuid(item.id)||!count(item.timestamp_utc)||!hash(item.sha256)
        ||typeof item.filename!=='string'||new TextEncoder().encode(item.filename).length>1024||typeof item.state_or_mode!=='string'||new TextEncoder().encode(item.state_or_mode).length>64))throw new Error('Invalid workbook history');
      continuation(value.next_cursor,'history');
      return <>{value.items.length===0&&<p>No workbook activity in this page.</p>}
        <BoundedCollection caption="Workbook runs and exports (UTC)" rows={value.items.map(item=>({id:item.kind+':'+item.id,cells:[item.kind,item.filename,
          new Date(item.timestamp_utc*1000).toISOString(),item.state_or_mode,item.sha256,
          item.kind==='run'?<button type="button" onClick={()=>setOpened(item.id)}>Open run {item.id}</button>:<span>Export identity: {item.id}</span>]}))}
          next={value.next_cursor!==null} onNext={()=>{setOpened(null);setCursor(value.next_cursor);}}/>
        {opened&&<WorkbookRun key={opened} id={opened}/>}</>;
    }}/></section>;
}
