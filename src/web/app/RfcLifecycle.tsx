import {OwnerProjection} from '../components/OwnerProjection';

const fields=[
  ['summary_text','summary_evidence_id','Summary'],
  ['external_created_at_utc','external_created_evidence_id','External creation UTC'],
  ['creator_text','creator_evidence_id','Creator'],
  ['customer_account_number_text','customer_account_number_evidence_id','Source Customer account number'],
  ['customer_account_name_text','customer_account_name_evidence_id','Source Customer account name'],
  ['severity_text','severity_evidence_id','Severity'],
  ['status_text','status_evidence_id','Status'],
  ['owner_external_id_text','owner_external_id_evidence_id','External owner ID'],
  ['owner_name_text','owner_name_evidence_id','Owner name'],
  ['l1_handler_name_text','l1_handler_name_evidence_id','L1 handler'],
  ['l2_handler_name_text','l2_handler_name_evidence_id','L2 handler'],
  ['last_update_utc','last_update_evidence_id','Last source update UTC'],
] as const;
type Lifecycle=Readonly<{rfc_id:string;accepted_source_state:Record<string,unknown>;local_archive_state:'active'|'archived';terminal_epoch_id:string|null;warnings:readonly string[]}>;
const text=(value:unknown):value is string=>typeof value==='string';
const evidence=(value:unknown)=>text(value)&&value.length>0;
const instant=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>=0&&Number(value)<=8640000000000;
/** Render the accepted owner projection; source status grants no action authority. */
export function RfcLifecycle({id}:{id:string}) {
  return <section aria-label="RFC accepted source and lifecycle"><h2>Accepted source and lifecycle</h2>
    <OwnerProjection<Lifecycle> path={`/api/v1/tickets/rfcs/${encodeURIComponent(id)}/lifecycle`} render={value=>{
      const source=value.accepted_source_state;
      const keys=[...fields.flatMap(([field,proof])=>[field,proof]),'status_class','status_authority','revision'];
      if(value.rfc_id!==id||!['active','archived'].includes(value.local_archive_state)||!source||typeof source!=='object'||Array.isArray(source)
        ||Object.keys(source).length!==keys.length||keys.some(key=>!Object.hasOwn(source,key))
        ||!Array.isArray(value.warnings)||value.warnings.length>200||value.warnings.some(warning=>!text(warning))
        ||(source.revision!==null&&(!Number.isSafeInteger(source.revision)||Number(source.revision)<1)))throw new Error('Invalid RFC lifecycle projection');
      for(const [field,proof] of fields){const fact=source[field],ref=source[proof];
        if((fact===null)!==(ref===null)||(ref!==null&&!evidence(ref))||(fact!==null&&
          (field==='external_created_at_utc'||field==='last_update_utc'?!instant(fact):!text(fact))))throw new Error('Invalid accepted source provenance');
      }
      const state=source.status_class;
      if(!text(state)||!['unknown','pre_implement','implement_eligible','terminal_closed','terminal_cancelled'].includes(state))throw new Error('Invalid source classification');
      const terminal=state==='terminal_closed'||state==='terminal_cancelled';
      if(source.revision===null&&(state!=='unknown'||fields.some(([field,proof])=>source[field]!==null||source[proof]!==null)))throw new Error('Missing accepted projection revision');
      if(state==='unknown'?(source.status_text!==null||source.status_authority!==null||source.status_evidence_id!==null||value.terminal_epoch_id!==null):
        (!text(source.status_text)||!text(source.status_authority)||!['enhanced_rfc','wfm_provisional'].includes(source.status_authority)||!evidence(source.status_evidence_id)))throw new Error('Invalid accepted status authority');
      if(terminal?!evidence(value.terminal_epoch_id):value.terminal_epoch_id!==null)throw new Error('Invalid terminal epoch');
      return <><p>Local archive state: {value.local_archive_state}. Local archive is independent of provider source status.</p>
        <p>Accepted source Status: {source.status_text===null?'Unknown':String(source.status_text)}. Classification: {String(state)}.</p>
        <p>Status authority: {source.status_authority===null?'Unknown':String(source.status_authority)}. Status evidence: {source.status_evidence_id===null?'None':String(source.status_evidence_id)}.</p>
        <p>Current terminal epoch: {value.terminal_epoch_id??'None'}.</p>
        {terminal&&<p>Accepted terminal source state does not establish that Task, Objective or Communication consequences have executed. Those consequences require the owner cascade review and command.</p>}
        <p>Source projection revision: {source.revision===null?'No accepted source projection':String(source.revision)}.</p>
        <p>Source Customer labels are descriptive evidence; canonical Customer identity remains a separate owner relationship.</p>
        <dl>{fields.map(([field,proof,label])=><div key={field}><dt>{label}</dt><dd>{source[field]===null?'Unknown':field==='external_created_at_utc'||field==='last_update_utc'?new Date(Number(source[field])*1000).toISOString():String(source[field])}
          {source[proof]!==null&&<p>Source evidence: {String(source[proof])}</p>}</dd></div>)}</dl>
        {value.warnings.map(warning=><p className="warning" key={warning}>{warning}</p>)}</>;
    }}/></section>;
}
