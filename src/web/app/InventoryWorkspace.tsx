import {useState} from 'react';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type StockUnit = Readonly<{spare_part_unit_id:string;local_tracking_id:string|null;bom_code:string;manufacturer_serial:string|null;
  condition_token:string;disposition_token:string;location_kind:string|null;location_ref_id:string|null;custody_text:string|null;
  active_task_allocation_id:string|null;compatibility_classification:'exact'|'candidate'|'incompatible'|'unknown';availability_blockers:readonly string[]}>;
type StockPage = Readonly<{items:readonly StockUnit[];continuation:unknown|null;exact_total:number}>;
type AttentionItem = Readonly<{attention_id:string;target_kind:string;target_id:string;attention_kind:string;severity:string;
  reason:string;next_governed_action:string}>;
type AttentionPage = Readonly<{items:readonly AttentionItem[];continuation:unknown|null;exact_total:number;as_of_utc:number}>;

function Stock() {
  const [cursor,setCursor]=useState<unknown|null>(null);
  const path='/api/v1/inventory/stock?limit=200'+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Stock"><h2>Stock</h2>
    <p>Physical units retain their own identity. Matching BOM or serial text does not establish identity or reserve a unit.</p>
    <OwnerProjection<StockPage> path={path} render={page=>{
      if (!Array.isArray(page.items)||page.items.length>200||!Number.isSafeInteger(page.exact_total)||page.exact_total<page.items.length) throw new Error('Invalid owner Stock page');
      const items:readonly StockUnit[]=page.items;
      if (items.some(item=>!Array.isArray(item.availability_blockers)||!['exact','candidate','incompatible','unknown'].includes(item.compatibility_classification))) throw new Error('Invalid owner eligibility projection');
      return <><p>{page.exact_total} physical units in the owner result; {items.length} on this page.</p>
        {items.length===0&&<p>No Stock units in this page.</p>}
        <BoundedCollection caption="Stock identity, physical state and owner eligibility" rows={items.map(item=>({id:item.spare_part_unit_id,cells:[
          <><strong>{item.local_tracking_id??'Internal unit identity'}</strong><p>{item.spare_part_unit_id}</p></>,item.bom_code,item.manufacturer_serial??'Unknown serial',
          `Condition: ${item.condition_token}`,`Disposition: ${item.disposition_token}`,
          `Location: ${item.location_kind??'Unknown'} / ${item.location_ref_id??'Unknown identity'}`,`Custody: ${item.custody_text??'Unknown'}`,
          `Current Task allocation: ${item.active_task_allocation_id??'None'}`,`Compatibility: ${item.compatibility_classification}`,
          item.availability_blockers.length?<ul>{item.availability_blockers.map(blocker=><li key={blocker}>Blocker: {blocker}</li>)}</ul>:<span>No owner availability blockers in this projection.</span>]}))}
          next={page.continuation!==null} onNext={()=>setCursor(page.continuation)}/></>;
    }}/>
  </section>;
}
function Attention() {
  const [asOf,setAsOf]=useState(()=>Math.floor(Date.now()/1000));const [cursor,setCursor]=useState<unknown|null>(null);
  const [refreshKey,setRefreshKey]=useState(0);
  const path=`/api/v1/inventory/attention?limit=200&as_of_utc=${asOf}`+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Inventory Needs Attention"><h2>Needs Attention</h2>
    <p>Unresolved obligations remain visible even when their related attempt is archived or terminal. Owner-projected attention does not record a logistics or physical consequence.</p>
    <button type="button" onClick={()=>{setCursor(null);setAsOf(Math.floor(Date.now()/1000));setRefreshKey(value=>value+1);}}>Refresh Inventory attention</button>
    <OwnerProjection<AttentionPage> path={path} refreshKey={refreshKey} render={page=>{
      if (!Array.isArray(page.items)||page.items.length>200||page.as_of_utc!==asOf||!Number.isSafeInteger(page.exact_total)||page.exact_total<page.items.length) throw new Error('Invalid owner attention page');
      const items:readonly AttentionItem[]=page.items;
      return <><p>{page.exact_total} owner attention items; {items.length} on this page. Evaluated at {new Date(asOf*1000).toISOString()}.</p>
        {items.length===0&&<p>No attention items in this owner page.</p>}
        <BoundedCollection caption="Inventory owner reasons and next governed actions" rows={items.map(item=>({id:item.attention_id,cells:[
          `Severity: ${item.severity}`,item.attention_kind,`${item.target_kind}: ${item.target_id}`,item.reason,`Next governed action: ${item.next_governed_action}`]}))}
          next={page.continuation!==null} onNext={()=>setCursor(page.continuation)}/></>;
    }}/>
  </section>;
}
export function InventoryWorkspace() {
  return <><Stock/><Attention/></>;
}
