import type {ReactNode} from 'react';
import {noteIdentity as identity} from './ticket-notes-intent';
const sourceFields=[['problem_summary','Problem Summary','text'],['report_date','Report Date UTC','instant'],
  ['customer_contact_label','Source Customer Contact label','text'],['customer_severity','Customer Severity','controlled'],
  ['current_handler_label','Source Current Handler','text'],['status','Source Status','controlled'],
  ['customer_org_label','Source Customer label','text'],['customer_account_code','Source Customer Account Code','text'],
  ['suspend_planned_end','Suspend planned end UTC','instant'],['suspension_duration','Suspension duration seconds','duration_seconds'],['last_update','Last source update UTC','instant']] as const;
type Field=Readonly<{observation_id:string;value_state:'usable'|'explicit_clear';value_kind:string;value:string|number|null;source_chronology_utc:number|null;precedence_basis:string;source_observation_field_id:string}>;
type Contact=Readonly<{relationship_id:string;contact_id:string;customer_org_context_id:string|null;supporting_sr_source_field_observation_id:string|null;origin_kind:string;opened_at_utc:number;contact_revision:number;contact_lifecycle_state:string;current_affiliation_id:string|null;current_affiliation_customer_org_id:string|null;alignment:'aligned'|'stale'|null}>;
type Customer=Readonly<{relationship_id:string;customer_org_id:string;origin_kind:string;opened_at_utc:number;customer_revision:number;customer_lifecycle_state:string}>;
type Context=Readonly<{service_request_id:string;customer:Customer|null;contacts:Readonly<{customer_contact:Contact|null;current_handler_reference:Contact|null}>;review_fingerprint:string;warnings:readonly string[]}>;
export type ServiceRequestContextFacts=Readonly<{service_request_id:string;source_projection:Readonly<{revision:number;fields:Readonly<Record<string,Field>>}>|null;reference_context:Context}>;
const integer=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>=0;
const nullableIdentity=(value:unknown)=>value===null||identity(value);
const proof=(value:unknown)=>typeof value==='string'&&value.length>0;
const lifecycle=(value:unknown)=>value==='active'||value==='archived';
const origin=(value:unknown)=>['manual_review','advanced_search_review','correction'].includes(String(value))&&typeof value==='string';
/** One GetServiceRequest snapshot supplies source authority and reference alignment. */
export function ServiceRequestContext({value,id}:{value:ServiceRequestContextFacts;id:string}) {
  let content:ReactNode;
  try {
    const source=value.source_projection,context=value.reference_context;
    if(value.service_request_id!==id||source===undefined||!context||context.service_request_id!==id||!context.contacts
      ||Object.keys(context.contacts).length!==2||!Object.hasOwn(context.contacts,'customer_contact')||!Object.hasOwn(context.contacts,'current_handler_reference')
      ||typeof context.review_fingerprint!=='string'||!/^[0-9a-f]{64}$/u.test(context.review_fingerprint)
      ||!Array.isArray(context.warnings)||context.warnings.length>200||context.warnings.some(code=>typeof code!=='string'))throw new Error('Invalid owner reference context');
    if(source!==null){
      if(!Number.isSafeInteger(source.revision)||source.revision<1||!source.fields||typeof source.fields!=='object'||Array.isArray(source.fields)
        ||Object.keys(source.fields).some(key=>!sourceFields.some(([field])=>field===key)))throw new Error('Invalid source field registry');
      for(const [key,,kind] of sourceFields){const field=source.fields[key];if(field===undefined)continue;
        if(!field||!identity(field.observation_id)||!proof(field.source_observation_field_id)||field.value_kind!==kind
          ||!['source_chronology','reviewed_correction'].includes(field.precedence_basis)
          ||(field.source_chronology_utc!==null&&!integer(field.source_chronology_utc))||(field.precedence_basis==='source_chronology'&&field.source_chronology_utc===null)
          ||(field.value_state==='explicit_clear'?(key!=='current_handler_label'||field.value!==null):
            (field.value_state!=='usable'||(kind==='text'||kind==='controlled'?typeof field.value!=='string':!integer(field.value)))))throw new Error('Invalid source authority');
      }
    }
    const customer=context.customer;
    if(customer!==null&&(!customer||!identity(customer.relationship_id)||!identity(customer.customer_org_id)||!origin(customer.origin_kind)
      ||!integer(customer.opened_at_utc)||!Number.isSafeInteger(customer.customer_revision)||customer.customer_revision<1||!lifecycle(customer.customer_lifecycle_state)))throw new Error('Invalid canonical Customer');
    for(const role of ['customer_contact','current_handler_reference'] as const){const contact=context.contacts[role];if(contact===null)continue;
      if(!contact||!identity(contact.relationship_id)||!identity(contact.contact_id)||!nullableIdentity(contact.customer_org_context_id)
        ||!nullableIdentity(contact.supporting_sr_source_field_observation_id)||!origin(contact.origin_kind)||!integer(contact.opened_at_utc)
        ||!Number.isSafeInteger(contact.contact_revision)||contact.contact_revision<1||!lifecycle(contact.contact_lifecycle_state)
        ||!nullableIdentity(contact.current_affiliation_id)||!nullableIdentity(contact.current_affiliation_customer_org_id)
        ||(contact.current_affiliation_id===null)!==(contact.current_affiliation_customer_org_id===null)
        ||(role==='customer_contact'?contact.alignment!==null:contact.alignment!=='aligned'&&contact.alignment!=='stale'))throw new Error('Invalid Contact relationship');
      if(role==='current_handler_reference'){
        const handler=source?.fields.current_handler_label;
        if(contact.supporting_sr_source_field_observation_id===null||contact.alignment==='aligned'&&(!handler||handler.value_state!=='usable'||handler.observation_id!==contact.supporting_sr_source_field_observation_id))throw new Error('Unsupported current Handler resolution');
      }
    }
    content=<><h3>Canonical Customer</h3><p>Customer identity: {customer?.customer_org_id??'Unresolved'}.</p>
      {customer&&<p>Relationship: {customer.relationship_id}. Origin: {customer.origin_kind}. Customer reference state: {customer.customer_lifecycle_state}; revision {customer.customer_revision}.</p>}
      <p>Source Customer labels and Account Code are descriptive evidence and do not establish or merge Customer identity.</p>
      {(['customer_contact','current_handler_reference'] as const).map(role=>{const contact=context.contacts[role];return <section key={role} aria-label={role==='customer_contact'?'Canonical Customer Contact':'Handler Contact resolution'}>
        <h3>{role==='customer_contact'?'Customer Contact':'Current Handler Contact resolution'}</h3>
        <p>{contact?(role==='current_handler_reference'?`Owner resolution: ${contact.alignment}.`:'Accepted Customer Contact relationship.'):'Unresolved Contact identity.'}</p>
        {contact&&<><p>{contact.alignment==='stale'?'Historical stale Contact identity':'Contact identity'}: {contact.contact_id}. Relationship: {contact.relationship_id}.</p>
          {contact.alignment==='stale'&&<p>This stale Contact resolution does not supply the current Handler assignment.</p>}
          <p>Immutable organization at use: {contact.customer_org_context_id??'Unknown'}.</p><p>Current Contact affiliation: {contact.current_affiliation_customer_org_id??'Unbound'}. Contact reference state: {contact.contact_lifecycle_state}; revision {contact.contact_revision}.</p>
          <p>Origin: {contact.origin_kind}. Supporting source observation: {contact.supporting_sr_source_field_observation_id??'None'}.</p></>}
      </section>;})}
      <h3>Accepted current source facts</h3><p>Source projection revision: {source?.revision??'No accepted source projection'}.</p>
      <dl>{sourceFields.map(([key,label,kind])=>{const field=source?.fields[key];return <div key={key}><dt>{label}</dt><dd>{!field?'No accepted value':field.value_state==='explicit_clear'?'Explicitly cleared by accepted source evidence':kind==='instant'?`UTC epoch seconds: ${field.value}`:String(field.value)}
        {field&&<p>Observation: {field.observation_id}. Source evidence: {field.source_observation_field_id}. Precedence: {field.precedence_basis}. Source chronology UTC epoch seconds: {field.source_chronology_utc??'Unknown'}.</p>}</dd></div>;})}</dl>
      {context.warnings.map(code=><p className="warning" key={code}>{code}</p>)}</>;
  }catch{content=<p role="alert">The accepted SR source/reference context is unavailable or malformed. Refresh owner state.</p>;}
  return <section aria-label="SR accepted source and references"><h2>Accepted source and references</h2>{content}</section>;
}
