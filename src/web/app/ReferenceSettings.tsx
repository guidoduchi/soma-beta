import {useSettingsNavigation,useSettingsQuery} from './SettingsWorkspace';
import {nextSettingsQuery,settingsIdentity} from './settings-intent';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type Kind='customer_organization'|'contact'|'dispatch_location';
type Summary=Readonly<{reference_type:Kind;reference_id:string;display_name:string;revision:number;lifecycle_state:'active'|'archived'}>;
type Page=Readonly<{items:readonly Summary[];continuation:unknown|null}>;
type Channel=Readonly<{contact_channel_id:string;channel_kind:string;value_text:string;lifecycle_state:string;revision:number}>;
type Detail=Readonly<{reference_type:Kind;reference_id:string;revision:number;lifecycle_state:'active'|'archived';projection:Readonly<{
  name:string;current_account_code?:Readonly<{value_text:string}>|null;account_code_history_count?:number;
  current_affiliation?:Readonly<{customer_org_id:string}>|null;active_channel_count?:number;
  current_address?:Readonly<{source:'STANDALONE'|'SITE';state:'READY'|'UNAVAILABLE';address_text:string|null;site_id:string|null}>;
}>}>;
const directories=[['customer_organization','customer-organizations','Customer Organizations'],['contact','contacts','Contacts'],
  ['dispatch_location','dispatch-locations','Dispatch Locations']] as const;

function Channels({id}:{id:string}) {
  const [path,setPath]=useSettingsQuery('channels',`/api/v1/reference/contacts/${encodeURIComponent(id)}/channels?limit=200&include_archived=false`);
  const archived=new URL(path,'http://127.0.0.1').searchParams.get('include_archived')==='true';
  return <section aria-label="Contact channels"><h4>Contact channels</h4>
    <label><input type="checkbox" checked={archived} data-focus-token="settings:channels:archived" onChange={event=>setPath(`/api/v1/reference/contacts/${encodeURIComponent(id)}/channels?limit=200&include_archived=${event.target.checked}`)}/>Include archived channels</label>
    <OwnerProjection<Readonly<{items:readonly Channel[];continuation:unknown|null;exact_count?:number|null}>> path={path} render={page=>{
      if(!Object.hasOwn(page,'continuation')||!Array.isArray(page.items)||page.items.length>200||page.items.some(item=>typeof item.contact_channel_id!=='string'
        ||typeof item.value_text!=='string'||item.channel_kind!=='email'||!['active','archived'].includes(item.lifecycle_state)
        ||(!archived&&item.lifecycle_state!=='active')))throw new Error('Invalid owner channel page');
      const next=nextSettingsQuery(path,'channels',page.continuation);
      return <><p>{page.items.length} channels on this page. A channel value alone does not select a recipient.</p>
        <BoundedCollection caption="Owner Contact channels" rows={page.items.map(item=>({id:item.contact_channel_id,cells:[
          item.channel_kind,item.value_text,`Lifecycle: ${item.lifecycle_state}`,`Revision: ${item.revision}`]}))}
          next={page.continuation!==null} returnScrollToken="channels" nextFocusToken="settings:channels:next" onNext={()=>setPath(next)}/></>;
    }}/></section>;
}
function AccountHistory({id}:{id:string}) {
  const [path,setPath]=useSettingsQuery('accountHistory',`/api/v1/reference/customer-organizations/${encodeURIComponent(id)}/customer-account-code/history?limit=200`);
  type Claim=Readonly<{customer_org_identifier_id:string;value_text:string;lifecycle_state:string;created_at_utc:number;superseded_at_utc:number|null}>;
  return <OwnerProjection<Readonly<{items:readonly Claim[];continuation:unknown|null;exact_count:number}>> path={path} render={page=>{
    if(!Object.hasOwn(page,'continuation')||!Array.isArray(page.items)||page.items.length>200||!Number.isSafeInteger(page.exact_count)||page.exact_count<page.items.length)throw new Error('Invalid owner account history');
    const next=nextSettingsQuery(path,'accountHistory',page.continuation);
    return <><h4>Account Code history</h4><p>{page.exact_count} historical claims; {page.items.length} on this page. Shared descriptive evidence does not merge Customer identities.</p>
      <BoundedCollection caption="Owner Account Code claims" rows={page.items.map(item=>({id:item.customer_org_identifier_id,cells:[
        item.value_text,item.lifecycle_state,`Created UTC epoch: ${item.created_at_utc}`,`Superseded UTC epoch: ${item.superseded_at_utc??'Current'}`]}))}
        next={page.continuation!==null} returnScrollToken="accountHistory" nextFocusToken="settings:accountHistory:next" onNext={()=>setPath(next)}/></>;
  }}/>;
}
function ReferenceDetail({kind,resource,id}:{kind:Kind;resource:string;id:string}) {
  const navigation=useSettingsNavigation();const history=navigation.intent.accountHistory;
  return <OwnerProjection<Detail> path={`/api/v1/reference/${resource}/${encodeURIComponent(id)}`} render={value=>{
    if(value.reference_id!==id||value.reference_type!==kind||!Number.isSafeInteger(value.revision)||value.revision<1
      ||!['active','archived'].includes(value.lifecycle_state)||typeof value.projection?.name!=='string')throw new Error('Invalid owner reference detail');
    const projection=value.projection;
    if(kind==='customer_organization'&&(!Object.hasOwn(projection,'current_account_code')
      ||!Number.isSafeInteger(projection.account_code_history_count)||projection.account_code_history_count!<0
      ||(projection.current_account_code!==null&&typeof projection.current_account_code?.value_text!=='string')))throw new Error('Missing owner account projection');
    if(kind==='contact'&&(!Object.hasOwn(projection,'current_affiliation')
      ||!Number.isSafeInteger(projection.active_channel_count)||projection.active_channel_count!<0
      ||(projection.current_affiliation!==null&&typeof projection.current_affiliation?.customer_org_id!=='string')))throw new Error('Missing owner affiliation projection');
    if(kind==='dispatch_location'&&(!projection.current_address||!['STANDALONE','SITE'].includes(projection.current_address.source)
      ||!['READY','UNAVAILABLE'].includes(projection.current_address.state)
      ||(projection.current_address.state==='READY'&&typeof projection.current_address.address_text!=='string')))throw new Error('Missing owner address projection');
    return <><h3>{projection.name}</h3><p>Reference identity: {id}. Revision: {value.revision}. Lifecycle: {value.lifecycle_state}.</p>
      {value.lifecycle_state==='archived'&&<p>Historical reference. New-work eligibility requires explicit owner reactivation and validation.</p>}
      {kind==='customer_organization'&&<><p>Current Account Code claim: {projection.current_account_code?.value_text??'None'}.</p>
        <p>Account Code claims in owner history: {projection.account_code_history_count}.</p>
        <button type="button" data-focus-token="settings:accountHistory:toggle" onClick={()=>navigation.history(!history)}>{history?'Hide':'Show'} Account Code history</button>
        {history&&<AccountHistory id={id}/>}</>}
      {kind==='contact'&&<><p>Current Customer affiliation: {projection.current_affiliation?.customer_org_id??'Unbound'}.</p>
        <p>Active channels in owner projection: {projection.active_channel_count}.</p><Channels id={id}/></>}
      {kind==='dispatch_location'&&<><p>Current address source: {projection.current_address?.source==='SITE'?'Site-derived':'Standalone'}.</p>
        <p>Current address: {projection.current_address?.state==='READY'?projection.current_address.address_text:'Unavailable from the address owner'}.</p>
        <p>Delivery, pickup and return roles belong to the consuming logistics operation.</p></>}
    </>;
  }}/>;
}
function Directory({kind,resource,label}:{kind:Kind;resource:string;label:string}) {
  const slot=kind==='customer_organization'?'customers':kind==='contact'?'contacts':'dispatch';
  const navigation=useSettingsNavigation();const opened=navigation.intent.opened[slot];
  const [path,setPath]=useSettingsQuery(slot,`/api/v1/reference/${resource}?limit=200`);
  return <section aria-label={label}><h2>{label}</h2><p>Active owner references. Similar names do not establish identity.</p>
    <OwnerProjection<Page> path={path} render={page=>{
      if(!Object.hasOwn(page,'continuation')||!Array.isArray(page.items)||page.items.length>200||page.items.some(item=>item.reference_type!==kind||item.lifecycle_state!=='active'
        ||!settingsIdentity(item.reference_id)||typeof item.display_name!=='string'||!Number.isSafeInteger(item.revision)||item.revision<1))throw new Error('Invalid owner reference page');
      const next=nextSettingsQuery(path,slot,page.continuation);
      return <><p>{page.items.length} active references on this page.</p>
        <BoundedCollection caption={`${label} owner identities`} rows={page.items.map(item=>({id:item.reference_id,cells:[
          item.display_name,item.reference_id,`Revision: ${item.revision}`,<button type="button" data-focus-token={'settings:open:'+item.reference_id} onClick={()=>navigation.open(slot,item.reference_id)}>Open {item.display_name}</button>]}))}
          next={page.continuation!==null} returnScrollToken={slot} nextFocusToken={'settings:'+slot+':next'} onNext={()=>setPath(next)}/></>;
    }}/>{opened&&<ReferenceDetail key={opened} kind={kind} resource={resource} id={opened}/>}</section>;
}
export function ReferenceSettings() {return <>{directories.map(([kind,resource,label])=><Directory key={kind} kind={kind} resource={resource} label={label}/>)}</>;}
