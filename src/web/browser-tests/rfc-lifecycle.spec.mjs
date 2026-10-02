import {test,expect} from '@playwright/test';
const id='33333333-3333-4333-8333-333333333333';
function lifecycle(state='terminal_cancelled',archive='active') {
  const source={};
  for(const [field,proof] of [['summary_text','summary_evidence_id'],['external_created_at_utc','external_created_evidence_id'],
    ['creator_text','creator_evidence_id'],['customer_account_number_text','customer_account_number_evidence_id'],['customer_account_name_text','customer_account_name_evidence_id'],
    ['severity_text','severity_evidence_id'],['owner_external_id_text','owner_external_id_evidence_id'],['owner_name_text','owner_name_evidence_id'],
    ['l1_handler_name_text','l1_handler_name_evidence_id'],['l2_handler_name_text','l2_handler_name_evidence_id'],['last_update_utc','last_update_evidence_id']]){source[field]=null;source[proof]=null;}
  return {rfc_id:id,accepted_source_state:{...source,status_text:state==='unknown'?null:'Synthetic provider status',status_class:state,
    status_authority:state==='unknown'?null:'enhanced_rfc',status_evidence_id:state==='unknown'?null:'synthetic-status-evidence',revision:state==='unknown'?null:2},
    local_archive_state:archive,terminal_epoch_id:state.startsWith('terminal_')?'synthetic-terminal-epoch':null,warnings:['RFC_CUSTOMER_UNRESOLVED']};
}
async function setup(page,projection,{fail=false}={}) {
  const methods=[];
  await page.route('**/api/v1/**',route=>{
    methods.push(route.request().method());const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/lifecycle'))return route.fulfill(fail?{status:503,json:{code:'SYNTHETIC_UNAVAILABLE'}}:{json:projection});
    if(path.startsWith('/api/v1/tickets/'))return route.fulfill({json:{rfc_id:id,rfc_no:'NC00000000000001',revision:1,hierarchy_role:'standalone',customer_org_id:null,local_archive_state:'active',direct_service_request_count:0,device_reference_count:0,subordinate_count:0,warnings:[]}});
    return route.fulfill({status:503,json:{code:'SYNTHETIC_UNAVAILABLE'}});
  });
  await page.goto('http://127.0.0.1:4174/tickets/rfc/'+id);return methods;
}
test('RFC Overview reads accepted source provenance separately from archive and consequences with inert source text',async({page})=>{
  const projection=lifecycle();projection.accepted_source_state.summary_text='<script>window.syntheticUnsafe=true</script>';projection.accepted_source_state.summary_evidence_id='synthetic-summary-evidence';
  projection.accepted_source_state.customer_account_name_text='Synthetic descriptive customer';projection.accepted_source_state.customer_account_name_evidence_id='synthetic-customer-evidence';
  const methods=await setup(page,projection);const panel=page.getByRole('region',{name:'RFC accepted source and lifecycle'});
  await expect(panel).toContainText('Classification: terminal_cancelled');await expect(panel).toContainText('Local archive state: active');
  await expect(panel).toContainText('does not establish');await expect(panel).toContainText('synthetic-terminal-epoch');
  await expect(panel).toContainText('synthetic-summary-evidence');await expect(panel).toContainText('<script>window.syntheticUnsafe=true</script>');
  await expect(panel).toContainText('canonical Customer identity remains a separate owner relationship');expect(await page.evaluate(()=>window.syntheticUnsafe)).toBeUndefined();
  await expect(page.getByText('Canonical Customer identity: Unresolved.',{exact:true})).toBeVisible();
  expect(methods.every(method=>method==='GET')).toBe(true);await expect(panel.getByRole('button')).toHaveCount(0);
});
test('Archived RFC with nonterminal source remains explicitly distinct at narrow width',async({page})=>{
  await page.setViewportSize({width:480,height:900});await setup(page,lifecycle('implement_eligible','archived'));
  const panel=page.getByRole('region',{name:'RFC accepted source and lifecycle'});await expect(panel).toContainText('Local archive state: archived');
  await expect(panel).toContainText('Classification: implement_eligible');await expect(panel).toContainText('Current terminal epoch: None');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('No accepted source projection renders unknown facts without classifying archive as terminal',async({page})=>{
  await setup(page,lifecycle('unknown','archived'));const panel=page.getByRole('region',{name:'RFC accepted source and lifecycle'});
  await expect(panel).toContainText('Accepted source Status: Unknown');await expect(panel).toContainText('No accepted source projection');
  await expect(panel).toContainText('Current terminal epoch: None');
});
for(const corruption of ['provenance','classification','epoch','missing','nonstring','revision'])test(`RFC lifecycle rejects ${corruption} instead of displaying unsupported source authority`,async({page})=>{
  const projection=lifecycle();if(corruption==='provenance')projection.accepted_source_state.summary_text='unproven';
  if(corruption==='classification')projection.accepted_source_state.status_class='complete';
  if(corruption==='epoch')projection.terminal_epoch_id=null;if(corruption==='missing')delete projection.accepted_source_state.status_evidence_id;
  if(corruption==='nonstring')projection.accepted_source_state.status_authority=['enhanced_rfc'];
  if(corruption==='revision')projection.accepted_source_state.revision=null;
  await setup(page,projection);const panel=page.getByRole('region',{name:'RFC accepted source and lifecycle'});
  await expect(panel.getByRole('alert')).toContainText('owner projection could not be rendered');await expect(panel).not.toContainText('synthetic-terminal-epoch');
});
test('RFC Back refetches accepted terminal reversal without retaining a source epoch or claiming inverse consequences',async({page})=>{
  const projection=lifecycle();await setup(page,projection);const panel=page.getByRole('region',{name:'RFC accepted source and lifecycle'});
  await expect(panel).toContainText('synthetic-terminal-epoch');await page.getByRole('link',{name:'Tickets',exact:true}).click();
  projection.accepted_source_state.status_class='implement_eligible';projection.accepted_source_state.status_text='Synthetic reversed status';projection.terminal_epoch_id=null;
  await page.goBack();await expect(panel).toContainText('Synthetic reversed status');await expect(panel).toContainText('Current terminal epoch: None');
  await expect(panel).not.toContainText('synthetic-terminal-epoch');
});
test('RFC lifecycle query failure keeps the independent RFC detail and tabs available',async({page})=>{
  await setup(page,lifecycle(),{fail:true});await expect(page.getByRole('heading',{name:'RFC NC00000000000001'})).toBeVisible();
  await expect(page.getByRole('region',{name:'RFC accepted source and lifecycle'}).getByRole('alert')).toContainText('owning query is unavailable');
  await page.getByRole('tab',{name:'Related RFCs',exact:true}).click();await expect(page.getByRole('heading',{name:'Related RFCs',exact:true})).toBeVisible();
});
