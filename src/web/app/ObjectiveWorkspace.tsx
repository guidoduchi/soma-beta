import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {objectiveCollectionQuery,groupingCollectionQuery,type ReturnState} from './router';
import {filterFingerprint} from '../data/query-controller';
import {OwnerProjection} from '../components/OwnerProjection';
import {SelectableCollection} from '../components/SelectableCollection';
import {BoundedCollection} from '../components/BoundedCollection';
import {UiStore, emptySelection} from '../state/ui-store';
import {GroupingProposalList} from './GroupingProposalList';

type Interval = Readonly<{start_utc: number; end_utc: number}>;
type Aggregate = Readonly<{execution_state: string; aggregate_outcome: string | null; actual_start_utc: number | null;
  actual_end_utc: number | null; attention_reason: string | null; included_task_count: number; excluded_task_count: number}>;
type ReadTime = Readonly<{as_of_utc: number; effective_review_state: string; due_unreviewed: boolean; reason_codes: readonly string[]}>;
type Summary = Readonly<{objective_id: string; tracking_handle: string; revision: number; derived_envelope: Interval;
  aggregate_state: Aggregate; read_time_projection: ReadTime; archived: boolean}>;
type ObjectivePage = Readonly<{items: readonly Summary[]; continuation: unknown | null; exact_total: number; as_of_utc: number}>;
type Membership = Readonly<{task_id: string; display_name: string; task_kind: string; accepted_plan: Interval;
  accepted_plan_revision_id: string; current_plan_revision_id: string; current_plan_revision: number; plan_membership_mismatch: boolean}>;
type Detail = Readonly<{objective_id: string; tracking_handle: string; revision: number; derived_envelope: Interval | null;
  aggregate_state: Aggregate | null; read_time_projection: ReadTime | null; membership: readonly Membership[];
  member_exact_count: number; member_continuation: unknown | null; superseded_by_objective_id: string | null;
  archive: Readonly<{archived: boolean}>; review?: Readonly<{review_fingerprint:string;
    current:Readonly<{objective_review_event_id:string;review_fingerprint:string;derived_outcome:string}>|null;
    latest:Readonly<{objective_review_event_id:string;review_fingerprint:string;derived_outcome:string;reviewed_at_utc:number;
      reason_code:string|null;stale:boolean}>|null}>}>;
function objectiveReview(review:Detail['review']) {
  if(review===undefined)return <p>Objective review evidence is unavailable from the owner projection.</p>;
  if(!review||!/^[0-9a-f]{64}$/u.test(review.review_fingerprint)||!Object.hasOwn(review,'current')||!Object.hasOwn(review,'latest'))throw new Error('Invalid owner review projection');
  for(const event of [review.current,review.latest]) {
    if(event!==null&&(typeof event.objective_review_event_id!=='string'||!event.objective_review_event_id
      ||!/^[0-9a-f]{64}$/u.test(event.review_fingerprint)||typeof event.derived_outcome!=='string'||!event.derived_outcome))throw new Error('Invalid owner review event');
  }
  if(review.latest!==null&&(typeof review.latest.stale!=='boolean'||(review.latest.reason_code!==null&&typeof review.latest.reason_code!=='string')))throw new Error('Invalid owner review freshness');
  return <section aria-label="Objective review evidence"><h2>Objective review evidence</h2>
    <p>{review.current===null?'No currently valid Objective review.':`Current owner-reviewed outcome: ${review.current.derived_outcome}. Review event: ${review.current.objective_review_event_id}.`}</p>
    {review.latest===null?<p>No Objective review event recorded.</p>:<>
      <p>Latest review event: {review.latest.objective_review_event_id}. Recorded outcome: {review.latest.derived_outcome}. Reviewed at (UTC): {instant(review.latest.reviewed_at_utc)}.</p>
      <p>Owner freshness: {review.latest.stale?'Stale':'Current'}. Reason: {review.latest.reason_code??'None recorded'}.</p>
      {review.latest.stale&&<p className="warning">This preserved review is stale and does not establish the current reviewed outcome.</p>}
    </>}
  </section>;
}
function instant(value: number | null): string {
  if (value === null) return 'Unknown';
  if (!Number.isSafeInteger(value) || value < 0) throw new Error('Invalid owner instant');
  return new Date(value * 1000).toISOString();
}
function interval(value: Interval | null): string {return value ? `${instant(value.start_utc)} to ${instant(value.end_utc)}` : 'No accepted interval';}
function readTime(value: ReadTime | null, asOf: number) {
  if (value === null) return <p>Read-time attention projection unavailable for this historical state.</p>;
  if (value.as_of_utc !== asOf || !Array.isArray(value.reason_codes)) throw new Error('Read-time projection identity mismatch');
  return <><p>Read-time review attention: {value.effective_review_state}. Evaluated at {instant(value.as_of_utc)}.</p>
    {value.due_unreviewed && <p className="warning">Due and unreviewed. This read-time warning does not record execution or a reviewed outcome.</p>}
    {value.reason_codes.map(reason => <p className="warning" key={reason}>{reason}</p>)}</>;
}
export function ObjectiveWorkspace({navigate,restored=null,onReturnState}: {navigate: (path: string) => void;restored?:ReturnState|null;
  onReturnState?:(capture:()=>ReturnState|null)=>void}) {
  const restoredQuery=restored?.route==='/objectives'?objectiveCollectionQuery(restored.collectionQuery):null;
  const root=useRef<HTMLDivElement>(null);const fingerprint=useRef<{path:string;value:string}|null>(null);
  const [notice,setNotice]=useState<string|null>(restored&&!restoredQuery?'The previous collection query is unavailable; the first current page is shown.':null);
  const [asOf, setAsOf] = useState(() => restoredQuery?.asOf??Math.floor(Date.now() / 1000));
  const [cursor, setCursor] = useState<unknown | null>(()=>restoredQuery?.cursor??null);
  const [refreshKey,setRefreshKey]=useState(0);
  const validGrouping=restoredQuery&&groupingCollectionQuery(restored?.groupingQuery);
  const [showGrouping,setShowGrouping]=useState(Boolean(validGrouping));
  const [groupingQuery,setGroupingQuery]=useState(()=>validGrouping?restored!.groupingQuery!:'/api/v1/grouping/proposals?limit=200');
  const store = useMemo(()=>{
    const value=new UiStore({selection:restoredQuery&&restored?{...emptySelection,active_id:restored.activeId,selected_id:restored.selectedId,
      member_ids:restored.memberIds}:emptySelection,tab:'List',pane:'work',filters:{},scrollAnchors:{},dirty:false,errors:{},focusToken:restoredQuery?restored?.focusToken??null:null});
    if(restoredQuery&&restored?.collectionOrder)value.rememberCollectionOrder(restored.collectionOrder);return value;
  },[]);
  const path = `/api/v1/objectives?limit=200&as_of_utc=${asOf}` + (cursor === null ? '' : '&cursor=' + encodeURIComponent(JSON.stringify(cursor)));
  useEffect(()=>{let current=true;void filterFingerprint({query:path}).then(value=>{if(current)fingerprint.current={path,value};});return()=>{current=false;};},[path]);
  useEffect(()=>{onReturnState?.(()=>{
    const hash=fingerprint.current;if(!hash||hash.path!==path||objectiveCollectionQuery(path)===null)return null;const state=store.getSnapshot();
    return {route:'/objectives',filterFingerprint:hash.value,activeId:state.selection.active_id,selectedId:state.selection.selected_id,
      memberIds:state.selection.member_ids,collectionQuery:path,collectionOrder:store.getCollectionOrder(),focusToken:state.focusToken,groupingQuery:showGrouping?groupingQuery:null,
      scrollAnchor:JSON.stringify({list:root.current?.querySelector('[aria-label="Records"]')?.scrollTop??0,main:document.getElementById('main-content')?.scrollTop??0})};
  });},[path,store,onReturnState,showGrouping,groupingQuery]);
  useLayoutEffect(()=>{
    const node=root.current;if(!node||!restoredQuery||!restored)return;
    let positions:{list:number;main:number}|null=null;
    try{
      if(restored.scrollAnchor&&restored.scrollAnchor.length<=256){const parsed=JSON.parse(restored.scrollAnchor);
        if(parsed&&Object.keys(parsed).length===2&&['list','main'].every(key=>typeof parsed[key]==='number'&&Number.isFinite(parsed[key])&&parsed[key]>=0))positions=parsed;}
    }catch{/* Missing scroll intent keeps the visible current position. */}
    let observer:MutationObserver|null=null;
    const stop=()=>{observer?.disconnect();observer=null;};
    const apply=()=>{
      if(Array.from(node.querySelectorAll('[role="status"]')).some(element=>element.textContent?.startsWith('Loading accepted state.')))return;
      const collection=node.querySelector<HTMLElement>('[aria-label="Records"]');
      const controls=Array.from(node.querySelectorAll<HTMLElement>('[data-focus-token]'));
      const focus=controls.find(element=>element.dataset.focusToken===restored.focusToken&&element.getClientRects().length>0&&!element.matches(':disabled'));
      const fallback=controls.find(element=>element.dataset.rowId===store.getSnapshot().selection.active_id)??collection??document.getElementById('main-content');
      if(restored.focusToken){(focus??fallback)?.focus({preventScroll:true});if(!focus)setNotice('The previous control is unavailable; focus returned to the nearest eligible row or collection.');}
      if(positions){if(collection)collection.scrollTop=positions.list;const main=document.getElementById('main-content');if(main)main.scrollTop=positions.main;}
      stop();
    };
    observer=new MutationObserver(apply);observer.observe(node,{childList:true,subtree:true,characterData:true});apply();
    for(const event of ['pointerdown','keydown','wheel','touchstart'])node.addEventListener(event,stop,{capture:true,once:true});
    return()=>{stop();for(const event of ['pointerdown','keydown','wheel','touchstart'])node.removeEventListener(event,stop,true);};
  },[]);
  return <div ref={root} onFocusCapture={event=>{const control=event.target.closest<HTMLElement>('[data-focus-token]');
    if(control&&event.currentTarget.contains(control))store.dispatch({focusToken:control.dataset.focusToken??null});}}>
    {notice&&<p role="status">{notice}</p>}<h2>Accepted Objective list</h2><p>Envelope and execution remain separate owner projections. Times below are labelled UTC.</p>
    <button type="button" data-focus-token="objective:refresh" onClick={() => {setCursor(null); setAsOf(Math.floor(Date.now() / 1000));setRefreshKey(value=>value+1);}}>Refresh Objective attention</button>
    <OwnerProjection<ObjectivePage> path={path} refreshKey={refreshKey} render={page => {
      if (!Array.isArray(page.items) || page.items.length > 200 || page.as_of_utc !== asOf || !Number.isSafeInteger(page.exact_total) || page.exact_total < page.items.length) throw new Error('Invalid owner Objective page');
      const items: readonly Summary[] = page.items;
      const byId = new Map(items.map(item => [item.objective_id,item]));
      const rows = items.map(item => ({id:item.objective_id,eligible:true,route:{record_type:'OBJECTIVE',record_id:item.objective_id,revision_token:String(item.revision)}}));
      return <><p>{page.exact_total} accepted Objectives in the owner result; {page.items.length} on this page.</p>
        {page.items.length === 0 && <p>No accepted Objectives in this page.</p>}
        <SelectableCollection rows={rows} store={store} open={ref => navigate('/objectives/' + encodeURIComponent(ref.record_id))} render={row => {
          const value = byId.get(row.id)!;
          return <><strong>{value.tracking_handle}</strong><p>Membership-pinned Objective envelope: {interval(value.derived_envelope)}</p>
            <p>Accepted aggregate execution: {value.aggregate_state.execution_state}. Reviewed outcome: {value.aggregate_state.aggregate_outcome ?? 'Unreviewed'}.</p>
            <p>Archived: {String(value.archived)}. Included Tasks: {value.aggregate_state.included_task_count}; excluded Tasks: {value.aggregate_state.excluded_task_count}.</p>
            {readTime(value.read_time_projection,asOf)}</>;
        }}/>{page.continuation !== null && <button type="button" data-focus-token="objective:next" onClick={() => {store.dispatch({selection:emptySelection}); setCursor(page.continuation);}}>Next Objective page</button>}</>;
    }}/><button type="button" data-focus-token="grouping:toggle" aria-expanded={showGrouping} onClick={()=>setShowGrouping(value=>!value)}>{showGrouping?'Hide':'Show'} grouping proposals</button>
    {showGrouping&&<GroupingProposalList query={groupingQuery} onQuery={setGroupingQuery}/>}</div>;
}
export function ObjectiveDetail({id}: {id: string}) {
  const [asOf] = useState(() => Math.floor(Date.now() / 1000)); const [cursor,setCursor] = useState<unknown | null>(null);
  const path = `/api/v1/objectives/${encodeURIComponent(id)}?member_limit=200&as_of_utc=${asOf}`
    + (cursor === null ? '' : '&member_cursor=' + encodeURIComponent(JSON.stringify(cursor)));
  return <OwnerProjection<Detail> path={path} render={value => {
    if (value.objective_id !== id || !Array.isArray(value.membership) || value.membership.length > 200 || !Number.isSafeInteger(value.member_exact_count) || value.member_exact_count < value.membership.length) throw new Error('Invalid owner Objective detail');
    return <><h2>Objective {value.tracking_handle}</h2><p>Accepted revision: {value.revision}. Archived: {String(value.archive.archived)}.</p>
      {value.superseded_by_objective_id && <p>Superseded by Objective {value.superseded_by_objective_id}.</p>}
      <h2>Objective envelope</h2><p>Membership-pinned interval (UTC): {interval(value.derived_envelope)}</p>
      <h2>Actual execution</h2><p>Accepted aggregate state: {value.aggregate_state?.execution_state ?? 'Unavailable'}.</p>
      <p>Actual start: {instant(value.aggregate_state?.actual_start_utc ?? null)}. Actual end: {instant(value.aggregate_state?.actual_end_utc ?? null)}.</p>
      <p>Reviewed aggregate outcome: {value.aggregate_state?.aggregate_outcome ?? 'Unreviewed'}. Starting selected Tasks records Task execution only.</p>
      {readTime(value.read_time_projection,asOf)}
      {objectiveReview(value.review)}
      <h2>Member Tasks</h2><p>{value.member_exact_count} accepted members; {value.membership.length} on this page. This page does not define the complete membership.</p>
      <BoundedCollection caption="Membership-pinned plans and current revision context" rows={value.membership.map(member => ({id:member.task_id,
        cells:[member.display_name,member.task_kind,`Membership-pinned Task plan (UTC): ${interval(member.accepted_plan)}`,
          `Current operational Task plan revision: ${member.current_plan_revision}`,member.plan_membership_mismatch ? 'PLAN_MEMBERSHIP_MISMATCH: reviewed regrouping is required to change the pin.' : 'Current operational plan matches the membership pin.']}))}
        next={value.member_continuation !== null} onNext={() => setCursor(value.member_continuation)}/>
    </>;
  }}/>;
}
