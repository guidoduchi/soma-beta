import {useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {OwnerProjection} from '../components/OwnerProjection';
import {SelectableCollection} from '../components/SelectableCollection';
import {BoundedCollection} from '../components/BoundedCollection';
import {UiStore, emptySelection} from '../state/ui-store';
import {InfrastructureWorkbookActivity} from './InfrastructureWorkbookActivity';
import {infrastructureIntent,infrastructureQuery,infrastructureTabs as tabs,type InfrastructureIntent,type ReturnState} from './router';
import {filterFingerprint} from '../data/query-controller';
type Ref = Readonly<{kind:string;id:string}>;
type Node = Readonly<{kind:'site'|'room'|'rack'|'cloud_deployment'|'network_element'|'containment';id:string;label:string;parent_context_id:string|null;lifecycle:string|null;warning_codes:readonly string[]}>;
type Explorer = Readonly<{nodes:readonly Node[];next_cursor:unknown|null}>;
type Element = Readonly<{network_element_id:string;revision:number;lifecycle:string;operational_name:string;site:Ref;customer_org_id:string;
  placement:Readonly<{rack_id:string|null;u_start:number|null;u_span:number|null;revision:number;explicit_unracked:boolean}>;
  model:Ref|null;cloud_deployment:Ref|null;primary_ip:string|null;ip_count:number;containment_parent:Ref|null;
  containment_child_count:number;device_reference_count:number;installed_component_count:number;warning_codes:readonly string[]}>;
type Component = Readonly<{installed_component_id:string;state:string;bom_code:string|null;manufacturer_serial:string|null;slot_label:string|null;
  condition:string;device_part_unit_id:string|null;physical_consequence_id:string|null}>;
type Components = Readonly<{items:readonly Component[];next_cursor:unknown|null}>;
type HistoryValue = Readonly<{kind:'null'|'text'|'integer'|'boolean'|'entity_ref';text_value:string|null;integer_value:number|null;boolean_value:boolean|null;entity_ref:Ref|null}>;
type History = Readonly<{events:readonly {event_id:string;event_kind:string;recorded_at_utc:number;effective_at_utc:number|null;
  summary:Readonly<{changes:readonly {field:string;prior:HistoryValue;new:HistoryValue}[];reason_code:string|null;warning_codes:readonly string[]}>}[];next_cursor:unknown|null}>;
function historyValue(value:HistoryValue):string {
  switch(value.kind) {
    case 'null':return 'None';case 'text':return value.text_value??'Unknown text';case 'integer':return String(value.integer_value);
    case 'boolean':return String(value.boolean_value);case 'entity_ref':return value.entity_ref?`${value.entity_ref.kind}: ${value.entity_ref.id}`:'Unknown identity';
    default:throw new Error('Unknown owner history value');
  }
}
function ComponentsView({id,path,onPath}:{id:string;path:string;onPath:(path:string)=>void}) {
  return <OwnerProjection<Components> path={path} render={page=>{
    if (!Array.isArray(page.items)||page.items.length>200) throw new Error('Invalid component page');
    const next=withCursor(path,page.next_cursor);
    if(!infrastructureQuery(next,'components',id))throw new Error('Invalid component continuation');
    return <><p>Installed Component instances are separate from reusable Model/BOM compatibility. Removed components remain visible in the owner history.</p>
      {page.items.length===0&&<p>No Installed Components in this page.</p>}
      <BoundedCollection caption="Installed Component identities and physical evidence" rows={page.items.map(item=>({id:item.installed_component_id,cells:[
        item.installed_component_id,item.bom_code??'No BOM code',item.manufacturer_serial??'Unknown serial',item.slot_label??'Unknown slot',item.state,item.condition,
        `Device Part Unit: ${item.device_part_unit_id??'Unresolved'}`,`Inventory physical consequence: ${item.physical_consequence_id??'None'}`]}))}
        next={page.next_cursor!==null} returnScrollToken="components" nextFocusToken="infrastructure:components:next" onNext={()=>onPath(next)}/></>;
  }}/>;
}
function HistoryView({id,path,onPath}:{id:string;path:string;onPath:(path:string)=>void}) {
  // Five events with 32 maximally escaped old/new field values remain below
  // the existing transport bound. Continuation preserves the complete history.
  return <OwnerProjection<History> path={path} render={page=>{
    if (!Array.isArray(page.events)||page.events.length>5||page.events.some(item=>!Array.isArray(item.summary.changes)||item.summary.changes.length>32)) throw new Error('Invalid history page');
    const next=withCursor(path,page.next_cursor);
    if(!infrastructureQuery(next,'history',id))throw new Error('Invalid history continuation');
    const events:History['events']=page.events;
    return <>{page.events.length===0&&<p>No owner history events in this page.</p>}
      <BoundedCollection caption="Infrastructure event chronology (UTC)" rows={events.map(item=>({id:item.event_id,cells:[item.event_kind,
        new Date(item.recorded_at_utc*1000).toISOString(),item.effective_at_utc===null?'Unknown effective time':new Date(item.effective_at_utc*1000).toISOString(),
        item.summary.reason_code??'No reason code',item.summary.warning_codes.join(', '),
        <ul>{item.summary.changes.map((change,index)=><li key={index}>{change.field}: {historyValue(change.prior)} → {historyValue(change.new)}</li>)}</ul>]}))} next={page.next_cursor!==null} returnScrollToken="history" nextFocusToken="infrastructure:history:next" onNext={()=>onPath(next)}/></>;
  }}/>;
}
function NetworkElement({intent,onIntent}:{intent:InfrastructureIntent;onIntent:(intent:InfrastructureIntent)=>void}) {
  const id=intent.openedId!;const tab=intent.tab;const prefix=useId();
  function activate(name:typeof tabs[number]) {onIntent({...intent,tab:name,workbook:name==='Workbook Activity'&&intent.workbook===null?
    {history:'/api/v1/infrastructure/workbooks/history?limit=200',run:null,proposalId:null,candidatePage:0}:intent.workbook});}
  return <section aria-label="Opened Network Element" data-scroll-owner="y" data-return-scroll="detail" className="infrastructure-detail">
    <OwnerProjection<Element> path={'/api/v1/infrastructure/network-elements/'+encodeURIComponent(id)} render={value=>{
      if (value.network_element_id!==id||!Array.isArray(value.warning_codes)||value.warning_codes.length>32) throw new Error('Invalid Network Element identity');
      return <><h2>{value.operational_name}</h2><p>Network Element identity: {value.network_element_id}. Lifecycle: {value.lifecycle}. Accepted revision: {value.revision}.</p>
        <p>Site identity: {value.site.id}. Customer Organization: {value.customer_org_id}.</p>
        {value.warning_codes.map(warning=><p className="warning" key={warning}>{warning}</p>)}
        <div role="tablist" aria-label="Network Element sections">{tabs.map((name,index)=><button type="button" role="tab" key={name} aria-selected={tab===name} tabIndex={tab===name?0:-1}
          data-focus-token={'infrastructure:tab:'+name} id={`${prefix}-tab-${index}`} aria-controls={`${prefix}-panel-${index}`} onClick={()=>activate(name)} onKeyDown={event=>{
            if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
            event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
            activate(tabs[next]!);document.getElementById(`${prefix}-tab-${next}`)?.focus();
          }}>{name}</button>)}</div>
        {tabs.map((name,index)=><div role="tabpanel" key={name} hidden={tab!==name} id={`${prefix}-panel-${index}`} aria-labelledby={`${prefix}-tab-${index}`}>
          {name==='Summary'?<><h3>Identity and Model</h3><p>Model identity: {value.model?.id??'Unassigned'}</p>
            <h3>Component and Device Reference summaries</h3><p>Installed Components: {value.installed_component_count}. Resolved Device References: {value.device_reference_count}.</p>
            <p>Operational Device Reference identifiers retain their own identity after resolution.</p></>:
          name==='Placement'?<><h3>Physical Placement</h3><p>{value.placement.explicit_unracked?'Explicitly Unracked':`Rack: ${value.placement.rack_id}. U start: ${value.placement.u_start}. U span: ${value.placement.u_span}.`}</p>
            <p>Placement revision: {value.placement.revision}. Physical placement is separate from containment and Cloud assignment.</p></>:
          name==='Components'?<ComponentsView id={id} path={intent.components!} onPath={components=>onIntent({...intent,components})}/>:
          name==='IP Addresses'?<><h3>Descriptive IP inventory</h3><p>Active addresses: {value.ip_count}. Primary IP: {value.primary_ip??'No primary selected'}.</p>
            <p>Descriptive addresses do not establish connectivity or reachability. No automatic primary promotion is implied.</p></>:
          name==='Relationships'?<><h3>Containment</h3><p>Parent Network Element: {value.containment_parent?.id??'None'}. Child count: {value.containment_child_count}.</p>
            <h3>Cloud assignment</h3><p>Cloud Deployment: {value.cloud_deployment?.id??'Unassigned'}. Cloud is separate from physical placement.</p>
            <h3>Model relation</h3><p>Model identity: {value.model?.id??'Unassigned'}.</p></>:
          name==='History'?<HistoryView id={id} path={intent.history!} onPath={history=>onIntent({...intent,history})}/>:intent.workbook?
            <InfrastructureWorkbookActivity intent={intent.workbook} onIntent={workbook=>onIntent({...intent,workbook})}/>:null}
        </div>)}</>;
    }}/>
  </section>;
}
function withCursor(path:string,cursor:unknown|null):string {
  const url=new URL(path,'http://127.0.0.1');url.searchParams.delete('cursor');if(cursor!==null)url.searchParams.set('cursor',JSON.stringify(cursor));
  return url.pathname+url.search;
}
export function InfrastructureWorkspace({restored=null,onReturnState}:{restored?:ReturnState|null;onReturnState?:(capture:()=>ReturnState|null)=>void}) {
  const restoredIntent=restored?.route==='/infrastructure'?infrastructureIntent(restored.infrastructure):null;
  const [intent,setIntent]=useState<InfrastructureIntent>(()=>restoredIntent??{explorer:'/api/v1/infrastructure/tree?limit=200',openedId:null,tab:'Summary',components:null,history:null,workbook:null});
  const [refreshKey,setRefreshKey]=useState(0);const [notice,setNotice]=useState<string|null>(restored&&!restoredIntent?'The previous Infrastructure context is unavailable; the first current explorer page is shown.':null);
  const root=useRef<HTMLDivElement>(null);const fingerprint=useRef<{key:string;value:string}|null>(null);
  const store=useMemo(()=>{
    const value=new UiStore({selection:restoredIntent&&restored?{...emptySelection,active_id:restored.activeId,selected_id:restored.selectedId,member_ids:restored.memberIds}:emptySelection,
      tab:'Summary',pane:'work',filters:{},scrollAnchors:{},dirty:false,errors:{},focusToken:restoredIntent?restored?.focusToken??null:null});
    if(restoredIntent&&restored?.collectionOrder)value.rememberCollectionOrder(restored.collectionOrder);return value;
  },[]);
  const key=JSON.stringify(intent);
  useEffect(()=>{let current=true;void filterFingerprint({intent:key}).then(value=>{if(current)fingerprint.current={key,value};});return()=>{current=false;};},[key]);
  useEffect(()=>{onReturnState?.(()=>{
    const hash=fingerprint.current;if(!hash||hash.key!==key||infrastructureIntent(intent)===null)return null;const state=store.getSnapshot();
    const positions=Array.from(root.current?.querySelectorAll<HTMLElement>('[data-return-scroll]')??[]).map(element=>[element.dataset.returnScroll,element.scrollTop,element.scrollLeft]);
    return {route:'/infrastructure',filterFingerprint:hash.value,infrastructure:intent,activeId:state.selection.active_id,selectedId:state.selection.selected_id,
      memberIds:state.selection.member_ids,collectionOrder:store.getCollectionOrder(),focusToken:state.focusToken,
      scrollAnchor:JSON.stringify({main:document.getElementById('main-content')?.scrollTop??0,panes:positions})};
  });},[key,intent,store,onReturnState]);
  useLayoutEffect(()=>{
    const node=root.current;if(!node||!restoredIntent||!restored)return;
    let positions:{main:number;panes:[string,number,number][]}|null=null;
    const valid=(value:unknown)=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
    try {if(restored.scrollAnchor&&restored.scrollAnchor.length<=2048) {
      const value=JSON.parse(restored.scrollAnchor);
      if(value&&Object.keys(value).length===2&&valid(value.main)&&Array.isArray(value.panes)&&value.panes.length<=8
        &&value.panes.every((row:unknown)=>Array.isArray(row)&&row.length===3&&typeof row[0]==='string'&&row[0].length<=64&&valid(row[1])&&valid(row[2])))positions=value;
    }}catch{/* Invalid saved scroll intent keeps current positions. */}
    let observer:MutationObserver|null=null;let fallbackExplained=false;const stop=()=>{observer?.disconnect();observer=null;};
    const apply=()=>{
      if(Array.from(node.querySelectorAll('[role="status"]')).some(element=>/^Loading accepted state\./u.test(element.textContent??'')))return;
      if(restored.focusToken) {
        const control=Array.from(node.querySelectorAll<HTMLElement>('[data-focus-token]')).find(element=>element.dataset.focusToken===restored.focusToken&&element.getClientRects().length>0&&!element.matches(':disabled'));
        const fallback=Array.from(node.querySelectorAll<HTMLElement>('[data-row-id]')).find(element=>element.dataset.rowId===store.getSnapshot().selection.active_id)
          ??node.querySelector<HTMLElement>('[data-focus-token="infrastructure:refresh"]');
        (control??fallback)?.focus({preventScroll:true});
        if(!control&&!fallbackExplained) {
          fallbackExplained=true;setNotice('The previous Infrastructure control is unavailable; focus returned to the nearest row or Refresh explorer.');
          return; // Apply scroll only after the fallback notice has committed.
        }
      }
      if(positions) {
        const main=document.getElementById('main-content');if(main)main.scrollTop=positions.main;
        for(const [token,top,left] of positions.panes) {
          const element=Array.from(node.querySelectorAll<HTMLElement>('[data-return-scroll]')).find(item=>item.dataset.returnScroll===token);
          if(element){element.scrollTop=top;element.scrollLeft=left;}
        }
      }
      stop();
    };
    observer=new MutationObserver(apply);observer.observe(node,{childList:true,subtree:true,characterData:true});apply();
    for(const event of ['pointerdown','keydown','wheel','touchstart'])node.addEventListener(event,stop,{capture:true,once:true});
    return()=>{stop();for(const event of ['pointerdown','keydown','wheel','touchstart'])node.removeEventListener(event,stop,true);};
  },[]);
  const path=intent.explorer;
  return <div ref={root} onFocusCapture={event=>{const control=event.target.closest<HTMLElement>('[data-focus-token]');if(control)store.dispatch({focusToken:control.dataset.focusToken??null});}}>
    {notice&&<p role="status">{notice}</p>}<p>Contextual explorer. Physical placement, containment, and Cloud assignment represent separate facts.</p>
    <button type="button" data-focus-token="infrastructure:refresh" onClick={()=>setRefreshKey(value=>value+1)}>Refresh explorer</button>
    <div className="infrastructure-workspace"><section aria-label="Infrastructure contextual explorer" data-scroll-owner="y" data-return-scroll="explorer" className="infrastructure-explorer">
      <OwnerProjection<Explorer> path={path} refreshKey={refreshKey} render={page=>{
        if (!Array.isArray(page.nodes)||page.nodes.length>200) throw new Error('Invalid explorer page');
        const next=withCursor(path,page.next_cursor);if(!infrastructureQuery(next,'explorer'))throw new Error('Invalid explorer continuation');
        const nodes:readonly Node[]=page.nodes; const byId=new Map(nodes.map(node=>[`${node.kind}:${node.id}`,node]));
        return <>{nodes.length===0&&<p>No Infrastructure nodes in this page.</p>}
          <SelectableCollection store={store} rows={nodes.map(node=>({id:`${node.kind}:${node.id}`,eligible:true,
            route:node.kind==='network_element'||node.kind==='containment'?{record_type:'INFRASTRUCTURE',record_id:node.id,revision_token:null}:null}))}
            open={ref=>setIntent({...intent,openedId:ref.record_id,tab:'Summary',components:`/api/v1/infrastructure/network-elements/${ref.record_id}/components?limit=200`,
              history:`/api/v1/infrastructure/history?target_kind=network_element&target_id=${ref.record_id}&limit=5`,workbook:null})} render={row=>{const node=byId.get(row.id)!;return <><strong>{node.label}</strong><p>{node.kind.replaceAll('_',' ')} — {node.lifecycle??'Unknown lifecycle'}</p>
              <p>{node.kind==='containment'?'Containment parent':'Physical/context parent'}: {node.parent_context_id??'None in this context'}.</p>
              {node.warning_codes.map(warning=><p className="warning" key={warning}>{warning}</p>)}</>;}}/>
          {page.next_cursor!==null&&<button type="button" data-focus-token="infrastructure:explorer:next" onClick={()=>{store.dispatch({selection:emptySelection});setIntent({...intent,explorer:next});}}>Next explorer page</button>}</>;
      }}/></section>{intent.openedId?<NetworkElement key={intent.openedId} intent={intent} onIntent={setIntent}/>:<section aria-label="Infrastructure detail"><h2>Select and open a Network Element</h2><p>A single click changes selection. Enter, double-click, or Open record opens its owner detail.</p></section>}</div></div>;
}
