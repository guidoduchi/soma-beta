import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import type {ReturnState} from './router';
import {WorkbenchShell, srTabs, rfcTabs} from '../components/WorkbenchShell';
import {OwnerProjection} from '../components/OwnerProjection';
import {UiStore, emptySelection} from '../state/ui-store';
import {TicketCommunications} from './TicketCommunications';
import {RfcLifecycle} from './RfcLifecycle';
type SrDetail = Readonly<{service_request_id: string; identity: {official_sr_no: string | null; local_sr_no: string | null}; revision: number;
  linked_root_rfc_count: number; device_reference_count: number; warnings: readonly string[]}>;
type RfcDetail = Readonly<{rfc_id: string; rfc_no: string; revision: number; hierarchy_role: string; local_archive_state: string;
  customer_org_id:string|null;direct_service_request_count: number; device_reference_count: number; subordinate_count: number; warnings: readonly string[]}>;
type NotePage = Readonly<{items: readonly {working_note_id: string; body_text: string; created_at_utc: number; updated_at_utc: number; created_by_local_user_profile_id: string}[]; continuation: unknown | null}>;
function Notes({type, id}: {type: 'service_request' | 'rfc'; id: string}) {
  const [cursor, setCursor] = useState<unknown | null>(null);
  // Ten maximum-size bodies including six-byte JSON escapes fit the existing
  // bounded transport. Paging preserves all owner notes without a global increase.
  const path = `/api/v1/tickets/${type}/${encodeURIComponent(id)}/notes?limit=10` + (cursor === null ? '' : '&cursor=' + encodeURIComponent(JSON.stringify(cursor)));
  return <OwnerProjection<NotePage> path={path} render={page => {
    if (!Array.isArray(page.items) || page.items.length > 10) return <p role="alert">The note page is outside its requested owner bound.</p>;
    return <><h2>Working Notes</h2>{page.items.length === 0 && <p>No active notes in this page.</p>}
      {page.items.map(note => <article key={note.working_note_id}><p style={{whiteSpace: 'pre-wrap'}}>{note.body_text}</p>
        <p>Created {new Date(note.created_at_utc * 1000).toISOString()}; updated {new Date(note.updated_at_utc * 1000).toISOString()}.</p>
        <p>Creator profile: {note.created_by_local_user_profile_id}</p></article>)}
      {page.continuation !== null && <button type="button" data-focus-token="notes:next" onClick={() => setCursor(page.continuation)}>Next notes</button>}</>;
  }}/>;
}
export function TicketWorkbench({id, type, onDirtyChange, restored, onReturnState}: {id: string; type: 'service_request' | 'rfc'; onDirtyChange: (dirty: boolean) => void; restored: ReturnState | null; onReturnState: (capture: () => ReturnState | null) => void}) {
  const root = useRef<HTMLDivElement>(null); const [returnNotice,setReturnNotice] = useState<string | null>(null);
  const store = useMemo(() => new UiStore({selection: restored ? {...emptySelection, active_id: restored.activeId, selected_id: restored.selectedId, member_ids: restored.memberIds} : emptySelection,
    tab: restored?.tab ?? 'Overview', pane: restored?.pane ?? 'work', filters: {}, scrollAnchors: {}, dirty: false, errors: {}, focusToken: restored?.focusToken ?? null}), [id, type, restored]);
  useEffect(() => {
    onReturnState(() => {
      const state = store.getSnapshot();
      // Detail workbenches have no filter input. Unknown future filters require
      // their owner-bound fingerprint before restoration can be registered.
      if (Object.keys(state.filters).length) return null;
      return {route: (type === 'rfc' ? '/tickets/rfc/' : '/tickets/sr/') + encodeURIComponent(id),
        filterFingerprint: '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a', activeId: state.selection.active_id,
        selectedId: state.selection.selected_id, memberIds: state.selection.member_ids,
        scrollAnchor: JSON.stringify({work:root.current?.querySelector('.work-pane')?.scrollTop??0,
          communications:root.current?.querySelector('.communication-pane')?.scrollTop??0,main:document.getElementById('main-content')?.scrollTop??0}),
        focusToken: state.focusToken, tab: state.tab, pane: state.pane};
    });
  }, [id, type, store, onReturnState]);
  useLayoutEffect(() => {
    const node=root.current;if (!node||!restored) return;
    let offsets:Record<string,number>|null=null;
    try {
      if (restored.scrollAnchor&&restored.scrollAnchor.length<=256) {
        const value=JSON.parse(restored.scrollAnchor) as Record<string,unknown>;
        if (Object.keys(value).length===3&&['work','communications','main'].every(key=>typeof value[key]==='number'&&Number.isFinite(value[key])&&(value[key] as number)>=0)) offsets=value as Record<string,number>;
      }
    } catch { /* A missing/evicted/incompatible context uses the visible fallback. */ }
    const focus=Array.from(node.querySelectorAll<HTMLElement>('[data-focus-token]')).find(element=>element.dataset.focusToken===restored.focusToken&&element.getClientRects().length>0&&!element.matches(':disabled'));
    if (focus) focus.focus({preventScroll:true});
    else if (restored.focusToken) {document.getElementById('main-content')?.focus({preventScroll:true});setReturnNotice('The previous control is unavailable; focus returned to the workbench.');}
    const apply=()=>{
      for (const [key,element] of [['work',node.querySelector('.work-pane')],['communications',node.querySelector('.communication-pane')],['main',document.getElementById('main-content')]] as const) {
        if (element&&offsets) element.scrollTop=offsets[key]??0;
      }
    };
    apply();
    // Owner data may arrive after mount. Reapply only until those scoped reads
    // settle, and stop immediately if the operator begins a new interaction.
    let observer:MutationObserver|null=null;
    const stop=()=>{observer?.disconnect();observer=null;};
    if (offsets&&typeof MutationObserver!=='undefined') {
      observer=new MutationObserver(()=>{apply();if (!Array.from(node.querySelectorAll('[role="status"]')).some(element=>element.textContent?.startsWith('Loading accepted state.'))) stop();});
      observer.observe(node,{childList:true,subtree:true,characterData:true});
    }
    for (const event of ['pointerdown','keydown','wheel','touchstart']) node.addEventListener(event,stop,{capture:true,once:true});
    return ()=>{stop();for(const event of ['pointerdown','keydown','wheel','touchstart']) node.removeEventListener(event,stop,true);};
  }, [restored]);
  return <div ref={root} onFocusCapture={event=>{
    const control=event.target.closest<HTMLElement>('[data-focus-token]');
    if (control&&event.currentTarget.contains(control)) store.dispatch({focusToken:control.dataset.focusToken??null});
  }}>{returnNotice&&<p role="status">{returnNotice}</p>}<WorkbenchShell store={store} onDirtyChange={onDirtyChange} tabs={type === 'service_request' ? srTabs : rfcTabs} renderTab={tab => {
    if (tab === 'Notes') return <Notes type={type} id={id}/>;
    if (tab !== 'Overview') return <><h2>{tab}</h2><p role="status">This owner projection is not yet bound to this surface.</p></>;
    return type === 'service_request' ? <OwnerProjection<SrDetail> path={'/api/v1/tickets/service-requests/' + encodeURIComponent(id)} render={value => <>
      <h2>Service Request {value.identity.official_sr_no ?? value.identity.local_sr_no}</h2><p>Accepted revision: {value.revision}</p>
      <p>Linked root RFCs: {value.linked_root_rfc_count}. Device References: {value.device_reference_count}.</p>
      {value.warnings.map(warning => <p className="warning" key={warning}>{warning}</p>)}</>}/> :
      <><OwnerProjection<RfcDetail> path={'/api/v1/tickets/rfcs/' + encodeURIComponent(id)} render={value => {
        if(value.rfc_id!==id||!Object.hasOwn(value,'customer_org_id')||(value.customer_org_id!==null&&
          (typeof value.customer_org_id!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value.customer_org_id))))throw new Error('Invalid RFC Customer identity');
        return <>
        <h2>RFC {value.rfc_no}</h2><p>Accepted revision: {value.revision}. Hierarchy role: {value.hierarchy_role}. Archive state: {value.local_archive_state}.</p>
        <p>Canonical Customer identity: {value.customer_org_id??'Unresolved'}.</p>
        <p>Direct Service Requests: {value.direct_service_request_count}. Device References: {value.device_reference_count}. Subordinates: {value.subordinate_count}.</p>
        {value.warnings.map(warning => <p className="warning" key={warning}>{warning}</p>)}</>;}}/><RfcLifecycle id={id}/></>;
  }} communications={<TicketCommunications key={type+':'+id} targetType={type==='service_request'?'SERVICE_REQUEST':'RFC'} targetId={id}/>}/></div>;
}
