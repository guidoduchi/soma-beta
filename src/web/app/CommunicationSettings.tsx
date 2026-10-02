import type {ReactNode} from 'react';
import {useSettingsNavigation,useSettingsQuery} from './SettingsWorkspace';
import {nextSettingsQuery,settingsIdentity,type SettingsSlot} from './settings-intent';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type Page<T>=Readonly<{items:readonly T[];next_cursor:unknown|null}>;
type Source=Readonly<{source_scope_id:string;revision:number;display_name:string;health_state:string;processing_enabled:boolean;
  selected_folders:readonly Readonly<{folder_key:string;role:'INBOX'|'SENT'|'OTHER';display_name:string}>[]}>;
type Coverage=Readonly<{source_scope_id:string;folders:readonly Readonly<{source_scope_id:string;folder_key:string;
  forward_state:'NONE'|'PARTIAL'|'COMPLETE_TO_HIGH_WATER'|'UNKNOWN';historical_state:'NONE'|'PARTIAL'|'BOUNDED_COMPLETE'|'UNKNOWN';
  high_water:Readonly<{checkpoint_kind:string;provider_time_source_epoch_ms:number|null}>|null;warnings:readonly string[]}>[];warnings:readonly string[]}>;
const counters=['discovered','inspected','matched','retained','unchanged','proposed','skipped','warnings','failures'] as const;
type Job=Readonly<{job_id:string;source_scope_id:string;job_kind:string;state:string;phase:string|null;percentage:number|null;
  counters:Readonly<Record<typeof counters[number],number>&{estimated_total:number|null}>;diagnostic_code:string|null}>;
type Orphan=Readonly<{communication_id:string;state:'ORPHAN_PENDING_PURGE'|'PURGED';purge_due_utc:number|null;reason_code:string;protected_dependency_count:number}>;
function count(value:number):number {if(!Number.isSafeInteger(value)||value<0)throw new Error('Invalid owner count');return value;}
function instant(value:number|null):string {if(value===null)return 'Unknown';return new Date(count(value)*1000).toISOString();}
function Paged<T>({label,path,slot,limit=100,row}:{label:string;path:string;slot:SettingsSlot;limit?:number;row:(item:T)=>Readonly<{id:string;cells:readonly ReactNode[]}>}) {
  const [query,setQuery]=useSettingsQuery(slot,path+`?limit=${limit}`);
  return <section aria-label={label}><h2>{label}</h2><OwnerProjection<Page<T>> path={query} render={page=>{
    if(!Array.isArray(page.items)||page.items.length>limit||!Object.hasOwn(page,'next_cursor'))throw new Error('Invalid owner Communication page');
    const next=nextSettingsQuery(query,slot,page.next_cursor);
    return <><p>{page.items.length} owner records on this page.</p><BoundedCollection caption={`${label} owner projection`} rows={page.items.map(row)}
      next={page.next_cursor!==null} returnScrollToken={slot} nextFocusToken={'settings:'+slot+':next'} onNext={()=>setQuery(next)}/></>;
  }}/></section>;
}
function SourceCoverage({id}:{id:string}) {
  return <OwnerProjection<Coverage> path={`/api/v1/communications/source-scopes/${encodeURIComponent(id)}/coverage`} render={value=>{
    if(value.source_scope_id!==id||!Array.isArray(value.folders)||value.folders.length>64||!Array.isArray(value.warnings))throw new Error('Invalid owner coverage');
    const folders:Coverage['folders']=value.folders;
    return <section aria-label="Selected Source coverage"><h3>Selected Source coverage</h3>
      <p>Forward high-water coverage and bounded historical coverage are separate facts. Provider checkpoint time is not message or business chronology.</p>
      {value.warnings.map(warning=><p className="warning" key={warning}>{warning}</p>)}
      <BoundedCollection caption="Per-folder owner coverage" rows={folders.map(folder=>{
        if(folder.source_scope_id!==id||!['NONE','PARTIAL','COMPLETE_TO_HIGH_WATER','UNKNOWN'].includes(folder.forward_state)
          ||!['NONE','PARTIAL','BOUNDED_COMPLETE','UNKNOWN'].includes(folder.historical_state)||!Array.isArray(folder.warnings)
          ||!Object.hasOwn(folder,'high_water'))throw new Error('Invalid owner folder coverage');
        if(folder.high_water!==null&&(!['POSITION','TIME','COMPOSITE'].includes(folder.high_water.checkpoint_kind)
          ||!Object.hasOwn(folder.high_water,'provider_time_source_epoch_ms')
          ||(folder.high_water.provider_time_source_epoch_ms!==null&&!Number.isSafeInteger(folder.high_water.provider_time_source_epoch_ms))))throw new Error('Invalid owner checkpoint');
        return {id:folder.folder_key,cells:[folder.folder_key,`Forward coverage: ${folder.forward_state}`,`Historical coverage: ${folder.historical_state}`,
          folder.high_water===null?'No supported high-water checkpoint':`Provider checkpoint kind: ${folder.high_water.checkpoint_kind}; provider epoch milliseconds: ${folder.high_water.provider_time_source_epoch_ms??'Unknown'}`,
          <ul>{folder.warnings.map(warning=><li key={warning}>{warning}</li>)}</ul>]};
      })} next={false} onNext={()=>{}}/></section>;
  }}/>;
}
const settings=[
  ['communications.processing_enabled','COMM_PROCESSING_ENABLED_V1','Automatic processing enabled',null,null],
  ['communications.processing_interval_minutes','COMM_PROCESSING_INTERVAL_V1','Processing interval in whole minutes',1,10080],
  ['communications.overlap_messages','COMM_OVERLAP_MESSAGES_V1','Overlap messages',0,500],
  ['communications.orphan_grace_minutes','COMM_ORPHAN_GRACE_V1','Orphan grace in whole minutes',1,525600],
  ['communications.auto_backfill_max_days','COMM_AUTO_BACKFILL_DAYS_V1','Automatic backfill maximum days',1,31],
] as const;
type Setting=Readonly<{setting_key:string;value:number|boolean;revision:number|null;source:'DEFAULT'|'PERSISTED';contract_name:string;contract_version:number;semantic_owner:string}>;
export function CommunicationSettings() {
  const navigation=useSettingsNavigation();const source=navigation.intent.opened.source;
  return <><h2>Processing schedule and retention</h2><p>Disabling processing does not suspend orphan housekeeping. Schedule changes govern future triggers; existing job configuration snapshots and pending purge due times remain owner evidence.</p>
    {settings.map(([key,contract,label,minimum,maximum])=><OwnerProjection<Setting> key={key} path={'/api/v1/settings/'+key} render={value=>{
      if(value.setting_key!==key||value.semantic_owner!=='LLD-09'||value.contract_name!==contract||value.contract_version!==1
        ||(value.source==='DEFAULT'?value.revision!==null:value.source!=='PERSISTED'||!Number.isSafeInteger(value.revision)||(value.revision??0)<1)
        ||(minimum===null?typeof value.value!=='boolean':typeof value.value!=='number'||!Number.isSafeInteger(value.value)||value.value<minimum||value.value>maximum))throw new Error('Invalid owner Communication setting');
      return <p>{label}: {String(value.value)}. Source: {value.source}; revision: {value.revision??'Default'}.</p>;
    }}/>)}
    {/* Eight maximum-size 64-folder summaries fit the existing 4 MiB transport,
        including worst-case JSON escaping of folder keys and display names. */}
    <Paged<Source> label="Communication Source Scopes" slot="sources" path="/api/v1/communications/source-scopes" limit={8} row={item=>{
      if(!settingsIdentity(item.source_scope_id)||!Array.isArray(item.selected_folders)||item.selected_folders.length>64||typeof item.processing_enabled!=='boolean'
        ||typeof item.display_name!=='string'||count(item.revision)<1||new Set(item.selected_folders.map(folder=>folder.folder_key)).size!==item.selected_folders.length
        ||item.selected_folders.some(folder=>typeof folder.folder_key!=='string'||typeof folder.display_name!=='string'||!['INBOX','SENT','OTHER'].includes(folder.role))
        ||!['READY','MISSING','LOCKED','CORRUPT','UNSUPPORTED','PARTIAL','UNPROBED'].includes(item.health_state))throw new Error('Invalid owner Source Scope');
      return {id:item.source_scope_id,cells:[item.display_name,`Source Scope identity: ${item.source_scope_id}`,`Revision: ${count(item.revision)}`,
        `Health: ${item.health_state}`,`Processing enabled: ${String(item.processing_enabled)}`,
        <ul>{item.selected_folders.map(folder=><li key={folder.folder_key}>{folder.display_name}; role {folder.role}; identity {folder.folder_key}</li>)}</ul>,
        <button type="button" data-focus-token={'settings:source:'+item.source_scope_id} onClick={()=>navigation.open('source',item.source_scope_id)}>View coverage for {item.display_name}</button>]};
    }}/>{source&&<SourceCoverage key={source} id={source}/>}
    <Paged<Job> label="Communication Jobs" slot="jobs" path="/api/v1/communications/jobs" row={job=>{
      if(!job.counters||!Object.hasOwn(job.counters,'estimated_total')||!Object.hasOwn(job,'percentage')||!Object.hasOwn(job,'phase')
        ||(job.phase!==null&&typeof job.phase!=='string'))throw new Error('Missing owner job counters');
      counters.forEach(key=>count(job.counters[key]));if(job.counters.estimated_total!==null)count(job.counters.estimated_total);
      if(job.percentage!==null&&(job.counters.estimated_total===null||job.counters.estimated_total===0||!Number.isFinite(job.percentage)||job.percentage<0||job.percentage>100))throw new Error('Unsupported owner percentage');
      return {id:job.job_id,cells:[job.job_kind,`State: ${job.state}`,`Phase: ${job.phase??'Unknown'}`,`Source Scope: ${job.source_scope_id}`,
        <ul>{counters.map(key=><li key={key}>{key}: {job.counters[key]}</li>)}</ul>,`Estimated total: ${job.counters.estimated_total??'Unknown'}`,
        job.percentage===null?'Percentage unavailable; progress uses exact counts':`Owner percentage: ${job.percentage}%`,job.diagnostic_code??'No diagnostic code']};
    }}/>
    <Paged<Orphan> label="Communication Housekeeping" slot="housekeeping" path="/api/v1/communications/housekeeping" row={item=>{
      if(!['ORPHAN_PENDING_PURGE','PURGED'].includes(item.state)||typeof item.reason_code!=='string'||!item.reason_code)throw new Error('Invalid owner retention state');
      return {id:item.communication_id,cells:[item.communication_id,`Retention state: ${item.state}`,`Purge due (UTC): ${instant(item.purge_due_utc)}`,
        `Reason: ${item.reason_code}`,`Observed protected dependencies: ${count(item.protected_dependency_count)}`,
        item.state==='PURGED'?'Message content is unavailable':'Dependency status is observational; the owner revalidates before purge']};
    }}/></>;
}
