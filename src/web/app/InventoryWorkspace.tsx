import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {inventoryCollectionQueries,type ReturnState} from './router';
import {filterFingerprint} from '../data/query-controller';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type StockUnit = Readonly<{spare_part_unit_id:string;local_tracking_id:string|null;bom_code:string;manufacturer_serial:string|null;
  condition_token:string;disposition_token:string;location_kind:string|null;location_ref_id:string|null;custody_text:string|null;
  active_task_allocation_id:string|null;compatibility_classification:'exact'|'candidate'|'incompatible'|'unknown';availability_blockers:readonly string[]}>;
type StockPage = Readonly<{items:readonly StockUnit[];continuation:unknown|null;exact_total:number}>;
type AttentionItem = Readonly<{attention_id:string;target_kind:string;target_id:string;attention_kind:string;severity:string;
  reason:string;next_governed_action:string}>;
type AttentionPage = Readonly<{items:readonly AttentionItem[];continuation:unknown|null;exact_total:number;as_of_utc:number}>;

function Stock({cursor,setCursor}:{cursor:unknown|null;setCursor:(cursor:unknown|null)=>void}) {
  const path='/api/v1/inventory/stock?limit=200'+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Stock"><h2>Stock</h2>
    <p>Physical units retain their own identity. Matching BOM or serial text does not establish identity or reserve a unit.</p>
    <OwnerProjection<StockPage> path={path} render={page=>{
      if (!Object.hasOwn(page,'continuation')||!Array.isArray(page.items)||page.items.length>200||!Number.isSafeInteger(page.exact_total)||page.exact_total<page.items.length) throw new Error('Invalid owner Stock page');
      if(inventoryCollectionQueries({stock:queryPath('stock',page.continuation),attention:queryPath('attention',null,0)})===null)throw new Error('Invalid owner Stock continuation');
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
          next={page.continuation!==null} nextFocusToken="inventory:stock:next" onNext={()=>setCursor(page.continuation)}/></>;
    }}/>
  </section>;
}
function Attention({asOf,setAsOf,cursor,setCursor}:{asOf:number;setAsOf:(time:number)=>void;cursor:unknown|null;setCursor:(cursor:unknown|null)=>void}) {
  const [refreshKey,setRefreshKey]=useState(0);
  const path=`/api/v1/inventory/attention?limit=200&as_of_utc=${asOf}`+(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
  return <section aria-label="Inventory Needs Attention"><h2>Needs Attention</h2>
    <p>Unresolved obligations remain visible even when their related attempt is archived or terminal. Owner-projected attention does not record a logistics or physical consequence.</p>
    <button type="button" data-focus-token="inventory:attention:refresh" onClick={()=>{setCursor(null);setAsOf(Math.floor(Date.now()/1000));setRefreshKey(value=>value+1);}}>Refresh Inventory attention</button>
    <OwnerProjection<AttentionPage> path={path} refreshKey={refreshKey} render={page=>{
      if (!Object.hasOwn(page,'continuation')||!Array.isArray(page.items)||page.items.length>200||page.as_of_utc!==asOf||!Number.isSafeInteger(page.exact_total)||page.exact_total<page.items.length) throw new Error('Invalid owner attention page');
      if(inventoryCollectionQueries({stock:queryPath('stock',null),attention:queryPath('attention',page.continuation,asOf)})===null)throw new Error('Invalid owner attention continuation');
      const items:readonly AttentionItem[]=page.items;
      return <><p>{page.exact_total} owner attention items; {items.length} on this page. Evaluated at {new Date(asOf*1000).toISOString()}.</p>
        {items.length===0&&<p>No attention items in this owner page.</p>}
        <BoundedCollection caption="Inventory owner reasons and next governed actions" rows={items.map(item=>({id:item.attention_id,cells:[
          `Severity: ${item.severity}`,item.attention_kind,`${item.target_kind}: ${item.target_id}`,item.reason,`Next governed action: ${item.next_governed_action}`]}))}
          next={page.continuation!==null} nextFocusToken="inventory:attention:next" onNext={()=>setCursor(page.continuation)}/></>;
    }}/>
  </section>;
}
function queryPath(kind:'stock'|'attention',cursor:unknown|null,asOf=0):string {
  return '/api/v1/inventory/'+kind+'?limit=200'+(kind==='attention'?'&as_of_utc='+asOf:'')
    +(cursor===null?'':'&cursor='+encodeURIComponent(JSON.stringify(cursor)));
}
export function InventoryWorkspace({restored=null,onReturnState}:{restored?:ReturnState|null;onReturnState?:(capture:()=>ReturnState|null)=>void}) {
  const intent=restored?.route==='/inventory'?inventoryCollectionQueries(restored.inventoryQueries):null;
  const [stockCursor,setStockCursor]=useState<unknown|null>(()=>intent?.stockCursor??null);
  const [attentionCursor,setAttentionCursor]=useState<unknown|null>(()=>intent?.attentionCursor??null);
  const [asOf,setAsOf]=useState(()=>intent?.asOf??Math.floor(Date.now()/1000));
  const [notice,setNotice]=useState<string|null>(restored&&!intent?'The previous Inventory query is unavailable; the first current pages are shown.':null);
  const root=useRef<HTMLDivElement>(null);const focus=useRef<string|null>(intent?restored?.focusToken??null:null);
  const fingerprint=useRef<{stock:string;attention:string;value:string}|null>(null);
  const stock=queryPath('stock',stockCursor);const attention=queryPath('attention',attentionCursor,asOf);
  useEffect(()=>{let current=true;void filterFingerprint({stock,attention}).then(value=>{if(current)fingerprint.current={stock,attention,value};});return()=>{current=false;};},[stock,attention]);
  useEffect(()=>{onReturnState?.(()=>{
    const hash=fingerprint.current;if(!hash||hash.stock!==stock||hash.attention!==attention)return null;
    const pane=(label:string)=>{const element=root.current?.querySelector<HTMLElement>('[aria-label="'+label+'"] .table-owner');return [element?.scrollTop??0,element?.scrollLeft??0];};
    return {route:'/inventory',filterFingerprint:hash.value,activeId:null,selectedId:null,memberIds:[],focusToken:focus.current,
      inventoryQueries:{stock,attention},scrollAnchor:JSON.stringify({main:document.getElementById('main-content')?.scrollTop??0,
        stock:pane('Stock'),attention:pane('Inventory Needs Attention')})};
  });},[stock,attention,onReturnState]);
  useLayoutEffect(()=>{
    const node=root.current;if(!node||!intent||!restored)return;
    let positions:{main:number;stock:number[];attention:number[]}|null=null;
    try {
      if(restored.scrollAnchor&&restored.scrollAnchor.length<=256) {
        const value=JSON.parse(restored.scrollAnchor);const valid=(number:unknown)=>typeof number==='number'&&Number.isFinite(number)&&number>=0;
        if(value&&Object.keys(value).length===3&&valid(value.main)&&[value.stock,value.attention].every(pair=>Array.isArray(pair)&&pair.length===2&&pair.every(valid)))positions=value;
      }
    }catch{/* Invalid scroll intent uses the visible current positions. */}
    let observer:MutationObserver|null=null;let fallbackExplained=false;const stop=()=>{observer?.disconnect();observer=null;};
    const apply=()=>{
      if(Array.from(node.querySelectorAll('[role="status"]')).some(element=>element.textContent?.startsWith('Loading accepted state.')))return;
      if(restored.focusToken) {
        const control=Array.from(node.querySelectorAll<HTMLElement>('[data-focus-token]')).find(element=>element.dataset.focusToken===restored.focusToken&&element.getClientRects().length>0&&!element.matches(':disabled'));
        const fallback=node.querySelector<HTMLElement>('[data-focus-token="inventory:attention:refresh"]')??document.getElementById('main-content');
        (control??fallback)?.focus({preventScroll:true});
        if(!control&&!fallbackExplained) {
          fallbackExplained=true;setNotice('The previous Inventory control is unavailable; focus returned to Refresh Inventory attention.');
          // Restore offsets after the notice commits, so browser scroll anchoring
          // cannot shift the saved position when the new status text is inserted.
          return;
        }
      }
      if(positions) {
        const main=document.getElementById('main-content');if(main)main.scrollTop=positions.main;
        for(const [label,pair] of [['Stock',positions.stock],['Inventory Needs Attention',positions.attention]] as const) {
          const element=node.querySelector<HTMLElement>('[aria-label="'+label+'"] .table-owner');if(element){element.scrollTop=pair[0]!;element.scrollLeft=pair[1]!;}
        }
      }
      stop();
    };
    observer=new MutationObserver(apply);observer.observe(node,{childList:true,subtree:true,characterData:true});apply();
    for(const event of ['pointerdown','keydown','wheel','touchstart'])node.addEventListener(event,stop,{capture:true,once:true});
    return()=>{stop();for(const event of ['pointerdown','keydown','wheel','touchstart'])node.removeEventListener(event,stop,true);};
  },[]);
  return <div ref={root} onFocusCapture={event=>{const control=event.target.closest<HTMLElement>('[data-focus-token]');if(control)focus.current=control.dataset.focusToken??null;}}>
    {notice&&<p role="status">{notice}</p>}<Stock cursor={stockCursor} setCursor={setStockCursor}/>
    <Attention cursor={attentionCursor} setCursor={setAttentionCursor} asOf={asOf} setAsOf={setAsOf}/></div>;
}
