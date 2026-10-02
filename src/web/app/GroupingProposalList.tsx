import {useState} from 'react';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';
import {groupingCollectionQuery} from './router';

// LLD-05 owner list projection, refined by the accepted grouping transport contract.
type Item=Readonly<{proposal_id:string;revision:number;proposal_kind:string;risk_tier:'normal'|'high';origin:string;
  state:'pending'|'accepted'|'rejected'|'superseded';input_fingerprint:string;affected_task_exact_count:number;
  affected_objective_exact_count:number;created_at_utc:number;owner_warnings:readonly string[];
  diff:Readonly<{proposal_kind:string;origin:string;risk_tier:string;task_change_count:number;objective_change_count:number}>}>;
type Page=Readonly<{items:readonly Item[];continuation:unknown|null;exact_total:number}>;
const states=['pending','accepted','rejected','superseded'] as const;
const risks=['normal','high'] as const;
const origins=['task_created','task_plan_changed','source_plan_adopted','manual_request','retry_created','objective_edit'] as const;
const kinds=['create','join','move','repin','consolidate','manual_merge','manual_split'] as const;
function count(value:number):number {if(!Number.isSafeInteger(value)||value<0)throw new Error('Invalid owner count');return value;}
export function GroupingProposalList({query,onQuery}:{query:string;onQuery:(query:string)=>void}) {
  const intent=groupingCollectionQuery(query);
  if(!intent)throw new Error('Invalid grouping collection intent');
  const [draft,setDraft]=useState(intent.filters);
  const path=(filters:typeof draft,cursor:unknown|null)=>{
    const parameters=new URLSearchParams({limit:'200'});
    for(const [key,value] of Object.entries(filters))if(value)parameters.set(key,value);
    if(cursor!==null)parameters.set('cursor',JSON.stringify(cursor));
    return '/api/v1/grouping/proposals?'+parameters.toString();
  };
  return <section aria-label="Grouping proposals"><h2>Grouping proposals</h2>
    <p>These are owner proposals for review. Viewing or filtering them does not change Task plans, Objective membership or reviewed outcomes.</p>
    <form onSubmit={event=>{event.preventDefault();onQuery(path(draft,null));}}>
      {([['state',states],['risk',risks],['origin',origins]] as const).map(([key,values])=><label key={key}>
        Proposal {key}<select data-focus-token={"grouping:filter:"+key} value={draft[key]} onChange={event=>setDraft({...draft,[key]:event.target.value})}>
          <option value="">All</option>{values.map(value=><option key={value} value={value}>{value}</option>)}
        </select></label>)}<button type="submit" data-focus-token="grouping:apply">Apply proposal filters</button>
    </form>
    <OwnerProjection<Page> path={query} render={page=>{
      if(!Array.isArray(page.items)||page.items.length>200||count(page.exact_total)<page.items.length||!Object.hasOwn(page,'continuation'))throw new Error('Invalid owner grouping page');
      if(groupingCollectionQuery(path(intent.filters,page.continuation))===null)throw new Error('Invalid owner grouping continuation');
      return <><p>{page.exact_total} proposals in the complete owner result; {page.items.length} on this page.</p>
        <BoundedCollection caption="Owner grouping proposal facts" rows={page.items.map(item=>{
          if(!states.includes(item.state)||!risks.includes(item.risk_tier)||!origins.includes(item.origin as typeof origins[number])
            ||!kinds.includes(item.proposal_kind as typeof kinds[number])||count(item.revision)<1||!/^[0-9a-f]{64}$/u.test(item.input_fingerprint)
            ||!Array.isArray(item.owner_warnings)||item.owner_warnings.length>2||new Set(item.owner_warnings).size!==item.owner_warnings.length
            ||item.owner_warnings.some((code:string)=>!['GROUPING_PROPOSAL_STALE','GROUPING_EQUIVALENT_REJECTION'].includes(code))
            ||!item.diff||item.diff.proposal_kind!==item.proposal_kind||item.diff.origin!==item.origin||item.diff.risk_tier!==item.risk_tier
            ||item.diff.task_change_count!==item.affected_task_exact_count||item.diff.objective_change_count!==item.affected_objective_exact_count)throw new Error('Invalid owner grouping list item');
          return {id:item.proposal_id,cells:[item.proposal_kind,`State: ${item.state}`,`Risk: ${item.risk_tier}`,`Origin: ${item.origin}`,
            `Revision: ${item.revision}`,`Affected Tasks: ${count(item.affected_task_exact_count)}; affected Objectives: ${count(item.affected_objective_exact_count)}`,
            `Created (UTC): ${new Date(count(item.created_at_utc)*1000).toISOString()}`,
            `Summary diff: ${item.diff.proposal_kind}; ${item.diff.task_change_count} Task changes; ${item.diff.objective_change_count} Objective changes`,
            <ul>{item.owner_warnings.map((code:string)=><li className="warning" key={code}>{code}</li>)}</ul>]};
        })} next={page.continuation!==null} nextFocusToken="grouping:next" onNext={()=>onQuery(path(intent.filters,page.continuation))}/></>;
    }}/></section>;
}
