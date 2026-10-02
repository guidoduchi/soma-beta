import {test,expect} from '@playwright/test';
const uuid=n=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const id=uuid(1),customer=uuid(2),contact=uuid(3),observation=uuid(4),other=uuid(5);
function field(value,kind='text',state='usable') {return {observation_id:observation,value_state:state,value_kind:kind,value,source_chronology_utc:1,precedence_basis:'source_chronology',source_observation_field_id:'synthetic-owner-evidence'};}
function relationship(alignment=null){return {relationship_id:uuid(6),contact_id:contact,customer_org_context_id:other,supporting_sr_source_field_observation_id:observation,
  origin_kind:'manual_review',opened_at_utc:1,contact_revision:2,contact_lifecycle_state:'active',current_affiliation_id:uuid(7),current_affiliation_customer_org_id:customer,alignment};}
function detail(){return {service_request_id:id,identity:{official_sr_no:'12345678',local_sr_no:null},revision:3,linked_root_rfc_count:0,device_reference_count:0,warnings:[],
  source_projection:{revision:2,fields:{current_handler_label:field('Synthetic source Handler'),customer_org_label:field('Synthetic descriptive Customer'),customer_account_code:field('SYNTHETIC-ACCOUNT'),status:field('Synthetic status','controlled')}},
  reference_context:{service_request_id:id,customer:{relationship_id:uuid(8),customer_org_id:customer,origin_kind:'manual_review',opened_at_utc:1,customer_revision:2,customer_lifecycle_state:'active'},
    contacts:{customer_contact:relationship(),current_handler_reference:relationship('aligned')},review_fingerprint:'a'.repeat(64),warnings:[]}};}
async function setup(page,value){const reads=[];await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;reads.push([route.request().method(),path]);
  return path===`/api/v1/tickets/service-requests/${id}`?route.fulfill({json:value}):route.fulfill({status:503,json:{code:'SYNTHETIC_UNAVAILABLE'}});
});await page.goto('http://127.0.0.1:4174/tickets/sr/'+id);return reads;}
test('SR Overview uses one owner snapshot and keeps canonical identities, organization-at-use and source labels distinct',async({page})=>{
  const value=detail();value.source_projection.fields.problem_summary=field('<script>window.syntheticUnsafe=true</script>');
  const reads=await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});
  await expect(panel).toContainText('Customer identity: '+customer);await expect(panel).toContainText('Synthetic descriptive Customer');
  await expect(panel).toContainText('SYNTHETIC-ACCOUNT');await expect(panel).toContainText('Immutable organization at use: '+other);
  await expect(panel).toContainText('Current Contact affiliation: '+customer);await expect(panel).toContainText('Owner resolution: aligned');
  await expect(panel).toContainText('Synthetic source Handler');await expect(panel).toContainText('synthetic-owner-evidence');
  await expect(panel).toContainText('<script>window.syntheticUnsafe=true</script>');expect(await page.evaluate(()=>window.syntheticUnsafe)).toBeUndefined();
  expect(reads.filter(([,path])=>path===`/api/v1/tickets/service-requests/${id}`)).toEqual([['GET',`/api/v1/tickets/service-requests/${id}`]]);
  expect(reads.some(([,path])=>path.endsWith('/references'))).toBe(false);expect(reads.every(([method])=>method==='GET')).toBe(true);await expect(panel.getByRole('button')).toHaveCount(0);
});
test('Stale Handler Contact remains historical context while current assignment comes from source',async({page})=>{
  const value=detail();value.reference_context.contacts.current_handler_reference.alignment='stale';value.reference_context.contacts.current_handler_reference.supporting_sr_source_field_observation_id=other;
  value.reference_context.warnings=['SR_HANDLER_REFERENCE_STALE'];await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});
  await expect(panel).toContainText('Historical stale Contact identity: '+contact);await expect(panel).toContainText('does not supply the current Handler assignment');
  await expect(panel).toContainText('Synthetic source Handler');await expect(panel).toContainText('SR_HANDLER_REFERENCE_STALE');
});
test('Explicit Handler clear is source evidence and retains stale Contact history without inventing an assignment',async({page})=>{
  const value=detail();value.source_projection.fields.current_handler_label=field(null,'text','explicit_clear');value.reference_context.contacts.current_handler_reference.alignment='stale';
  await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});await expect(panel).toContainText('Explicitly cleared by accepted source evidence');
  await expect(panel).toContainText('Historical stale Contact identity');await expect(panel).not.toContainText('Synthetic source Handler');
});
test('Unresolved canonical references stay unresolved beside descriptive source labels and owner warnings',async({page})=>{
  const value=detail();value.reference_context.customer=null;value.reference_context.contacts={customer_contact:null,current_handler_reference:null};value.reference_context.warnings=['SR_CUSTOMER_UNRESOLVED'];
  await page.setViewportSize({width:480,height:900});await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});
  await expect(panel).toContainText('Customer identity: Unresolved');await expect(panel).toContainText('Synthetic descriptive Customer');await expect(panel).toContainText('SR_CUSTOMER_UNRESOLVED');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
for(const bad of ['future','aligned-clear','observation','missing-role','malformed-role','affiliation','source-kind'])test(`SR context fails closed for ${bad} owner evidence`,async({page})=>{
  const value=detail();if(bad==='future')value.source_projection.fields.related_sr=field('inactive future field');
  if(bad==='aligned-clear')value.source_projection.fields.current_handler_label=field(null,'text','explicit_clear');
  if(bad==='observation')value.reference_context.contacts.current_handler_reference.supporting_sr_source_field_observation_id=other;
  if(bad==='missing-role')delete value.reference_context.contacts.customer_contact;if(bad==='malformed-role')value.reference_context.contacts.current_handler_reference.alignment=['aligned'];
  if(bad==='affiliation')value.reference_context.contacts.customer_contact.current_affiliation_id=null;if(bad==='source-kind')value.source_projection.fields.status.value_kind='text';
  await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});await expect(panel.getByRole('alert')).toContainText('unavailable or malformed');
  await expect(panel).not.toContainText('Synthetic source Handler');await expect(page.getByRole('heading',{name:'Service Request 12345678'})).toBeVisible();
});
test('SR Back refetches changed source Handler and owner mismatch warning without rewriting organization-at-use',async({page})=>{
  const value=detail();await setup(page,value);const panel=page.getByRole('region',{name:'SR accepted source and references'});await expect(panel).toContainText('Synthetic source Handler');
  await page.getByRole('link',{name:'Settings',exact:true}).click();value.source_projection.fields.current_handler_label=field('Changed synthetic Handler');value.reference_context.warnings=['SR_CONTACT_AFFILIATION_REVIEW_REQUIRED'];
  await page.goBack();await expect(panel).toContainText('Changed synthetic Handler');await expect(panel).toContainText('SR_CONTACT_AFFILIATION_REVIEW_REQUIRED');await expect(panel).toContainText('Immutable organization at use: '+other);
});
