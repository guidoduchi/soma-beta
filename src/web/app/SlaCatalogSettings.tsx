import type {ReactNode} from 'react';
import {useSettingsQuery} from './SettingsWorkspace';
import {nextSettingsQuery,type SettingsSlot} from './settings-intent';
import {OwnerProjection} from '../components/OwnerProjection';
import {BoundedCollection} from '../components/BoundedCollection';

type Base=Readonly<{lifecycle_state:'active'|'archived';revision:number}>;
type Product=Base&Readonly<{product_line_id:string;name:string}>;
type Contract=Base&Readonly<{contract_id:string;customer_org_id:string;name:string;contract_reference:string}>;
type Cpl=Base&Readonly<{contract_product_line_id:string;contract_id:string;product_line_id:string;customer_org_id:string;
  contract_reference:string;product_line_name:string;current_policy_revision_id:string|null;policy_revision_ordinal:number|null;policy_name:string|null}>;
type Mapping=Readonly<{mapping_id:string;mapping_key_type:string;normalized_key:string;customer_org_id:string;contract_product_line_id:string;active:boolean;revision:number}>;
type CatalogPage<T>=Readonly<{items:readonly T[];continuation:unknown|null}>;
function Catalog<T>({label,path,slot,row}:{label:string;path:string;slot:SettingsSlot;row:(item:T)=>Readonly<{id:string;cells:readonly ReactNode[]}>}) {
  const [query,setQuery]=useSettingsQuery(slot,path+'?limit=200');
  return <section aria-label={label}><h2>{label}</h2><OwnerProjection<CatalogPage<T>> path={query} render={page=>{
    if(!Array.isArray(page.items)||page.items.length>200||!Object.hasOwn(page,'continuation'))throw new Error('Invalid owner catalog page');
    const next=nextSettingsQuery(query,slot,page.continuation);
    return <><p>{page.items.length} owner catalog records on this page. This page does not represent the complete catalog.</p>
      <BoundedCollection caption={`${label} owner projections`} rows={page.items.map(row)} next={page.continuation!==null}
        returnScrollToken={slot} nextFocusToken={'settings:'+slot+':next'} onNext={()=>setQuery(next)}/></>;
  }}/></section>;
}
function state(value:Base):string {
  if(!['active','archived'].includes(value.lifecycle_state)||!Number.isSafeInteger(value.revision)||value.revision<1)throw new Error('Invalid owner catalog state');
  return `Lifecycle: ${value.lifecycle_state}. Revision: ${value.revision}`;
}
function fact(value:string):string {if(typeof value!=='string'||value.length===0)throw new Error('Missing owner catalog fact');return value;}
export function SlaCatalogSettings() {
  return <><p>Reusable Product Lines carry no global SLA policy. Current policy authority belongs to each Contract Product Line.</p>
    <Catalog<Product> label="Product Lines" slot="products" path="/api/v1/product-lines" row={item=>({id:fact(item.product_line_id),cells:[fact(item.name),item.product_line_id,state(item)]})}/>
    <Catalog<Contract> label="Customer Contracts" slot="contracts" path="/api/v1/contracts" row={item=>({id:fact(item.contract_id),cells:[fact(item.name),fact(item.contract_reference),
      `Customer identity: ${fact(item.customer_org_id)}`,item.contract_id,state(item)]})}/>
    <Catalog<Cpl> label="Contract Product Lines" slot="cpls" path="/api/v1/contract-product-lines" row={item=>{
      if(!Object.hasOwn(item,'current_policy_revision_id')||!Object.hasOwn(item,'policy_name')||!Object.hasOwn(item,'policy_revision_ordinal'))throw new Error('Missing owner policy projection');
      if(item.current_policy_revision_id!==null&&(typeof item.current_policy_revision_id!=='string'||!Number.isSafeInteger(item.policy_revision_ordinal)
        ||item.policy_revision_ordinal!<1||typeof item.policy_name!=='string'))throw new Error('Invalid owner policy projection');
      return {id:fact(item.contract_product_line_id),cells:[fact(item.product_line_name),`Reusable Product Line identity: ${fact(item.product_line_id)}`,
        `Owning Contract: ${fact(item.contract_reference)} / ${fact(item.contract_id)}`,`Customer identity: ${fact(item.customer_org_id)}`,state(item),
        item.current_policy_revision_id===null?'No current policy revision':`Current policy: ${item.policy_name??'Unnamed'} / ${item.current_policy_revision_id}; ordinal ${item.policy_revision_ordinal}`]};
    }}/>
    <Catalog<Mapping> label="Classification mappings" slot="mappings" path="/api/v1/sla/classification-mappings" row={item=>{
      if(typeof item.active!=='boolean'||!Number.isSafeInteger(item.revision)||item.revision<1)throw new Error('Invalid owner mapping state');
      return {id:fact(item.mapping_id),cells:[fact(item.mapping_key_type),fact(item.normalized_key),`Customer identity: ${fact(item.customer_org_id)}`,
        `Contract Product Line identity: ${fact(item.contract_product_line_id)}`,`Active: ${String(item.active)}. Revision: ${item.revision}`]};
    }}/></>;
}
