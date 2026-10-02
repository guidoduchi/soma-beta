import {test,expect} from '@playwright/test';
const id='55555555-5555-4555-8555-555555555555';
test('Inventory Stock retains blocked identity and attention uses one as_of instant across continuation without writes',async({page})=>{
  const requests=[];const instants=[];
  await page.route('**/api/v1/inventory/**',route=>{
    requests.push(route.request().method());const url=new URL(route.request().url());expect(url.searchParams.get('limit')).toBe('200');
    if(url.pathname.endsWith('/stock'))return route.fulfill({json:{items:[{spare_part_unit_id:id,local_tracking_id:'LSU-SYNTHETIC',bom_code:'SYNTHETIC-BOM',manufacturer_serial:'SYNTHETIC-SERIAL',
      condition_token:'faulty',disposition_token:'quarantined',location_kind:'unknown',location_ref_id:null,custody_text:'Synthetic custody',active_task_allocation_id:null,
      compatibility_classification:'unknown',availability_blockers:['SYNTHETIC_QUARANTINE']}],continuation:{synthetic:'stock-next'},exact_total:2}});
    const asOf=Number(url.searchParams.get('as_of_utc'));instants.push(asOf);
    return route.fulfill({json:{items:[{attention_id:'synthetic-attention-1',target_kind:'rma',target_id:id,attention_kind:'warehouse_rejected_resend_required',severity:'action_required',
      reason:'Synthetic terminal predecessor still has an open obligation.',next_governed_action:'Review resend'}],continuation:instants.length===1?{synthetic:'attention-next'}:null,exact_total:2,as_of_utc:asOf}});
  });
  await page.setViewportSize({width:480,height:900});await page.goto('http://127.0.0.1:4174/inventory');
  await expect(page.getByText('LSU-SYNTHETIC')).toBeVisible();await expect(page.getByText('Blocker: SYNTHETIC_QUARANTINE')).toBeVisible();
  const attention=page.getByRole('region',{name:'Inventory Needs Attention'});
  await expect(attention.getByText('Synthetic terminal predecessor still has an open obligation.')).toBeAttached();
  await attention.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>instants.length).toBe(2);
  expect(instants[0]).toBe(instants[1]);expect(requests).toEqual(['GET','GET','GET']);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Inventory attention rejects mismatched query identity without inventing current warnings',async({page})=>{
  await page.route('**/api/v1/inventory/stock?**',route=>route.fulfill({json:{items:[],continuation:null,exact_total:0}}));
  await page.route('**/api/v1/inventory/attention?**',route=>route.fulfill({json:{items:[],continuation:null,exact_total:0,as_of_utc:0}}));
  await page.goto('http://127.0.0.1:4174/inventory');await expect(page.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(page.getByText('No attention items in this owner page.')).toHaveCount(0);
});
