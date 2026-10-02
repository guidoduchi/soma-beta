import {useId, useMemo, useState} from 'react';
import {OwnerProjection} from '../components/OwnerProjection';
import {SelectableCollection} from '../components/SelectableCollection';
import {BoundedCollection} from '../components/BoundedCollection';
import {UiStore, emptySelection} from '../state/ui-store';
import {InfrastructureWorkbookActivity} from './InfrastructureWorkbookActivity';
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
const tabs=['Summary','Placement','Components','IP Addresses','Relationships','History','Workbook Activity'] as const;
function historyValue(value:HistoryValue):string {
  switch(value.kind) {
    case 'null':return 'None';case 'text':return value.text_value??'Unknown text';case 'integer':return String(value.integer_value);
    case 'boolean':return String(value.boolean_value);case 'entity_ref':return value.entity_ref?`${value.entity_ref.kind}: ${value.entity_ref.id}`:'Unknown identity';
    default:throw new Error('Unknown owner history value');
  }
}
function ComponentsView({id}:{id:string}) {
  const [cursor,setCursor]=useState<unknown|null>(null);
  const path=`/api/v1/infrastructure/network-elements/${encodeURIComponent(id)}/components?limit=200`
    +(cursor === null ? '' : '&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <OwnerProjection<Components> path={path} render={page=>{
    if (!Array.isArray(page.items)||page.items.length>200) throw new Error('Invalid component page');
    return <><p>Installed Component instances are separate from reusable Model/BOM compatibility. Removed components remain visible in the owner history.</p>
      {page.items.length===0&&<p>No Installed Components in this page.</p>}
      <BoundedCollection caption="Installed Component identities and physical evidence" rows={page.items.map(item=>({id:item.installed_component_id,cells:[
        item.installed_component_id,item.bom_code??'No BOM code',item.manufacturer_serial??'Unknown serial',item.slot_label??'Unknown slot',item.state,item.condition,
        `Device Part Unit: ${item.device_part_unit_id??'Unresolved'}`,`Inventory physical consequence: ${item.physical_consequence_id??'None'}`]}))}
        next={page.next_cursor!==null} onNext={()=>setCursor(page.next_cursor)}/></>;
  }}/>;
}
function HistoryView({id}:{id:string}) {
  const [cursor,setCursor]=useState<unknown|null>(null);
  // Five events with 32 maximally escaped old/new field values remain below
  // the existing transport bound. Continuation preserves the complete history.
  const path=`/api/v1/infrastructure/history?target_kind=network_element&target_id=${encodeURIComponent(id)}&limit=5`
    +(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <OwnerProjection<History> path={path} render={page=>{
    if (!Array.isArray(page.events)||page.events.length>5||page.events.some(item=>!Array.isArray(item.summary.changes)||item.summary.changes.length>32)) throw new Error('Invalid history page');
    const events:History['events']=page.events;
    return <>{page.events.length===0&&<p>No owner history events in this page.</p>}
      <BoundedCollection caption="Infrastructure event chronology (UTC)" rows={events.map(item=>({id:item.event_id,cells:[item.event_kind,
        new Date(item.recorded_at_utc*1000).toISOString(),item.effective_at_utc===null?'Unknown effective time':new Date(item.effective_at_utc*1000).toISOString(),
        item.summary.reason_code??'No reason code',item.summary.warning_codes.join(', '),
        <ul>{item.summary.changes.map((change,index)=><li key={index}>{change.field}: {historyValue(change.prior)} → {historyValue(change.new)}</li>)}</ul>]}))} next={page.next_cursor!==null} onNext={()=>setCursor(page.next_cursor)}/></>;
  }}/>;
}
function NetworkElement({id}:{id:string}) {
  const [tab,setTab]=useState<typeof tabs[number]>('Summary'); const prefix=useId();
  const [workbookVisited,setWorkbookVisited]=useState(false);
  function activate(name:typeof tabs[number]) {setTab(name);if(name==='Workbook Activity')setWorkbookVisited(true);}
  return <section aria-label="Opened Network Element" data-scroll-owner="y" className="infrastructure-detail">
    <OwnerProjection<Element> path={'/api/v1/infrastructure/network-elements/'+encodeURIComponent(id)} render={value=>{
      if (value.network_element_id!==id||!Array.isArray(value.warning_codes)||value.warning_codes.length>32) throw new Error('Invalid Network Element identity');
      return <><h2>{value.operational_name}</h2><p>Network Element identity: {value.network_element_id}. Lifecycle: {value.lifecycle}. Accepted revision: {value.revision}.</p>
        <p>Site identity: {value.site.id}. Customer Organization: {value.customer_org_id}.</p>
        {value.warning_codes.map(warning=><p className="warning" key={warning}>{warning}</p>)}
        <div role="tablist" aria-label="Network Element sections">{tabs.map((name,index)=><button type="button" role="tab" key={name} aria-selected={tab===name} tabIndex={tab===name?0:-1}
          id={`${prefix}-tab-${index}`} aria-controls={`${prefix}-panel-${index}`} onClick={()=>activate(name)} onKeyDown={event=>{
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
          name==='Components'?<ComponentsView id={id}/>:
          name==='IP Addresses'?<><h3>Descriptive IP inventory</h3><p>Active addresses: {value.ip_count}. Primary IP: {value.primary_ip??'No primary selected'}.</p>
            <p>Descriptive addresses do not establish connectivity or reachability. No automatic primary promotion is implied.</p></>:
          name==='Relationships'?<><h3>Containment</h3><p>Parent Network Element: {value.containment_parent?.id??'None'}. Child count: {value.containment_child_count}.</p>
            <h3>Cloud assignment</h3><p>Cloud Deployment: {value.cloud_deployment?.id??'Unassigned'}. Cloud is separate from physical placement.</p>
            <h3>Model relation</h3><p>Model identity: {value.model?.id??'Unassigned'}.</p></>:
          name==='History'?<HistoryView id={id}/>:workbookVisited?<InfrastructureWorkbookActivity/>:null}
        </div>)}</>;
    }}/>
  </section>;
}
export function InfrastructureWorkspace() {
  const [cursor,setCursor]=useState<unknown|null>(null); const [opened,setOpened]=useState<string|null>(null);
  const store=useMemo(()=>new UiStore({selection:emptySelection,tab:'Summary',pane:'work',filters:{},scrollAnchors:{},dirty:false,errors:{},focusToken:null}),[]);
  const path='/api/v1/infrastructure/tree?limit=200'+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <><p>Contextual explorer. Physical placement, containment, and Cloud assignment represent separate facts.</p>
    <div className="infrastructure-workspace"><section aria-label="Infrastructure contextual explorer" data-scroll-owner="y" className="infrastructure-explorer">
      <OwnerProjection<Explorer> path={path} render={page=>{
        if (!Array.isArray(page.nodes)||page.nodes.length>200) throw new Error('Invalid explorer page');
        const nodes:readonly Node[]=page.nodes; const byId=new Map(nodes.map(node=>[`${node.kind}:${node.id}`,node]));
        return <>{nodes.length===0&&<p>No Infrastructure nodes in this page.</p>}
          <SelectableCollection store={store} rows={nodes.map(node=>({id:`${node.kind}:${node.id}`,eligible:true,
            route:node.kind==='network_element'||node.kind==='containment'?{record_type:'INFRASTRUCTURE',record_id:node.id,revision_token:null}:null}))}
            open={ref=>setOpened(ref.record_id)} render={row=>{const node=byId.get(row.id)!;return <><strong>{node.label}</strong><p>{node.kind.replaceAll('_',' ')} — {node.lifecycle??'Unknown lifecycle'}</p>
              <p>{node.kind==='containment'?'Containment parent':'Physical/context parent'}: {node.parent_context_id??'None in this context'}.</p>
              {node.warning_codes.map(warning=><p className="warning" key={warning}>{warning}</p>)}</>;}}/>
          {page.next_cursor!==null&&<button type="button" onClick={()=>{store.dispatch({selection:emptySelection});setCursor(page.next_cursor);}}>Next explorer page</button>}</>;
      }}/></section>{opened?<NetworkElement key={opened} id={opened}/>:<section aria-label="Infrastructure detail"><h2>Select and open a Network Element</h2><p>A single click changes selection. Enter, double-click, or Open record opens its owner detail.</p></section>}</div></>;
}
