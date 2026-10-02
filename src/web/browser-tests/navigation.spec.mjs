import {test, expect} from '@playwright/test';

test('compiled application restores the same workbench tab on Back and Forward', async ({page}) => {
  const id = '11111111-1111-4111-8111-111111111111';
  // Synthetic owner DTOs isolate UI history; these are not operational database facts.
  await page.route('**/api/v1/tickets/service-requests/' + id, route => route.fulfill({json:{service_request_id:id,
    identity:{official_sr_no:'12345678',local_sr_no:null},revision:1,source_projection:null,reference_context:{},
    linked_root_rfc_count:0,device_reference_count:0,warnings:[]}}));
  await page.route('**/api/v1/tickets/service_request/' + id + '/notes?*', route => {
    expect(new URL(route.request().url()).searchParams.get('limit')).toBe('10');
    return route.fulfill({json:{items:[],continuation:null}});
  });
  await page.goto('http://127.0.0.1:4174/tickets/sr/' + id);
  await page.getByRole('tab', {name:'Notes',exact:true}).click();
  await expect(page.getByText('No active notes in this page.')).toBeVisible();
  await page.getByRole('link', {name:'Settings',exact:true}).click();
  await expect(page.getByRole('heading', {name:'Settings',exact:true})).toBeVisible();
  await page.goBack(); await expect(page.getByRole('tab', {name:'Notes',exact:true})).toHaveAttribute('aria-selected','true');
  await page.goForward(); await expect(page.getByRole('heading', {name:'Settings',exact:true})).toBeVisible();
  await page.goBack(); await expect(page.getByRole('tab', {name:'Notes',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByRole('tab', {name:'Notes',exact:true})).toBeFocused();
});

test('return restores pane scroll after asynchronous owner notes load without retaining their body in history',async({page})=>{
  const id='11111111-1111-4111-8111-111111111111';
  await page.route('**/api/v1/tickets/service-requests/'+id,route=>route.fulfill({json:{service_request_id:id,identity:{official_sr_no:'12345678',local_sr_no:null},
    revision:1,linked_root_rfc_count:0,device_reference_count:0,warnings:[]}}));
  await page.route('**/api/v1/tickets/service_request/'+id+'/notes?*',async route=>{
    await new Promise(resolve=>setTimeout(resolve,100));
    await route.fulfill({json:{items:[{working_note_id:'22222222-2222-4222-8222-222222222222',body_text:'SYNTHETIC_HISTORY_BODY_CANARY\n'.repeat(200),
      revision:1,created_at_utc:1000,updated_at_utc:1000,created_by_local_user_profile_id:id}],continuation:null}});
  });
  await page.goto('http://127.0.0.1:4174/tickets/sr/'+id);
  await page.getByRole('tab',{name:'Notes',exact:true}).click();await expect(page.getByText('Creator profile:')).toBeAttached();
  await page.locator('.work-pane').evaluate(node=>{node.scrollTop=600;});
  await page.getByRole('link',{name:'Settings',exact:true}).click();await page.goBack();
  await expect(page.getByRole('tab',{name:'Notes',exact:true})).toBeFocused();
  await expect.poll(()=>page.locator('.work-pane').evaluate(node=>node.scrollTop)).toBe(600);
  expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('SYNTHETIC_HISTORY_BODY_CANARY');
});
