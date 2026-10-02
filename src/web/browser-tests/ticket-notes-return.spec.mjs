import {test,expect} from '@playwright/test';
import {createHash} from 'node:crypto';
const id='11111111-1111-4111-8111-111111111111',note='22222222-2222-4222-8222-222222222222';
const cursor=type=>({version:1,query_id:'ListWorkingNotes',sort_registry_id:'WORKING_NOTE_CREATED_ID_ASC_V1',last_key_tuple:[1,note],
  filter_fingerprint:createHash('sha256').update(JSON.stringify({schema:'SOMA_WORKING_NOTE_FILTER_V1',ticket_id:id,ticket_type:type})).digest('hex'),null_order:'not_applicable'});
const row=(body='Synthetic current note',revision=1)=>({working_note_id:note,body_text:body,revision,created_at_utc:1,updated_at_utc:2,created_by_local_user_profile_id:id});
for(const [part,type] of [['sr','service_request'],['rfc','rfc']])test(`${type} note page survives tab changes and Back with current owner body, full cursor and async focus`,async({page})=>{
  let fresh=false;const reads=[];const continuation=cursor(type);
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());if(url.pathname.endsWith('/notes')){
      reads.push(url);await new Promise(resolve=>setTimeout(resolve,75));return route.fulfill({json:{items:[row(fresh?'Fresh synthetic note':'Initial synthetic note',fresh?2:1)],continuation}});
    }
    if(url.pathname.includes('/service-requests/'))return route.fulfill({json:{service_request_id:id,identity:{official_sr_no:'12345678',local_sr_no:null},revision:1,linked_root_rfc_count:0,device_reference_count:0,warnings:[]}});
    if(url.pathname===`/api/v1/tickets/rfcs/${id}`)return route.fulfill({json:{rfc_id:id,rfc_no:'NC00000000000001',revision:1,customer_org_id:null,hierarchy_role:'standalone',local_archive_state:'active',direct_service_request_count:0,device_reference_count:0,subordinate_count:0,warnings:[]}});
    return route.fulfill({status:503,json:{code:'SYNTHETIC_UNAVAILABLE'}});
  });
  await page.goto(`http://127.0.0.1:4174/tickets/${part}/${id}`);await page.getByRole('tab',{name:'Notes',exact:true}).click();
  await page.getByRole('button',{name:'Next notes'}).click();await expect.poll(()=>reads.some(url=>url.searchParams.has('cursor'))).toBe(true);
  await page.getByRole('tab',{name:'Overview',exact:true}).click();await page.getByRole('tab',{name:'Notes',exact:true}).click();
  await expect(page.getByText('Initial synthetic note',{exact:true})).toBeVisible();expect(JSON.parse(reads.at(-1).searchParams.get('cursor'))).toEqual(continuation);
  await page.getByRole('button',{name:'Next notes'}).focus();await page.getByRole('link',{name:'Settings',exact:true}).click();fresh=true;reads.length=0;await page.goBack();
  await expect(page.getByText('Fresh synthetic note',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Next notes'})).toBeFocused();
  expect(JSON.parse(reads[0].searchParams.get('cursor'))).toEqual(continuation);await expect(page.getByText('Accepted note revision: 2.',{exact:false})).toBeVisible();
  expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('Fresh synthetic');expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('cursor');
});
for(const bad of ['incomplete','foreign','missing','body','identity','chronology','duplicate'])test(`Notes rejects ${bad} owner page without exposing next-page intent`,async({page})=>{
  const continuation=cursor('service_request');let item=row();const response={items:[item],continuation};
  if(bad==='incomplete')continuation.last_key_tuple=[1];if(bad==='foreign')continuation.filter_fingerprint=cursor('rfc').filter_fingerprint;
  if(bad==='missing')delete response.continuation;if(bad==='body')item.body_text='x'.repeat(65537);if(bad==='identity')item.working_note_id='unclosed';
  if(bad==='chronology')item.updated_at_utc=0;if(bad==='duplicate')response.items.push({...item});
  await page.route('**/api/v1/**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/notes')?response:{service_request_id:id,identity:{official_sr_no:'12345678',local_sr_no:null},revision:1,linked_root_rfc_count:0,device_reference_count:0,warnings:[]}}));
  await page.goto('http://127.0.0.1:4174/tickets/sr/'+id);await page.getByRole('tab',{name:'Notes',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'owner projection could not be rendered'})).toBeVisible();await expect(page.getByRole('button',{name:'Next notes'})).toHaveCount(0);
});
test('Removed notes continuation restores focus to the logical workbench after current owner read',async({page})=>{
  let fresh=false;await page.route('**/api/v1/**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith('/notes')?{items:[row()],continuation:fresh?null:cursor('service_request')}:
    {service_request_id:id,identity:{official_sr_no:'12345678',local_sr_no:null},revision:1,linked_root_rfc_count:0,device_reference_count:0,warnings:[]}}));
  await page.goto('http://127.0.0.1:4174/tickets/sr/'+id);await page.getByRole('tab',{name:'Notes',exact:true}).click();await page.getByRole('button',{name:'Next notes'}).focus();
  await page.getByRole('link',{name:'Settings',exact:true}).click();fresh=true;await page.goBack();
  await expect(page.getByText('previous control is unavailable',{exact:false})).toBeVisible();await expect(page.locator('#main-content')).toBeFocused();
});
