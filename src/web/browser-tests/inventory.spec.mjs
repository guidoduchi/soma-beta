import {test,expect} from '@playwright/test';
const id='55555555-5555-4555-8555-555555555555';
const stockCursor={version:1,query_id:'StockEligibilityQuery',sort_registry_id:'INVENTORY_STOCK_COMPAT_LSU_ID_ASC_V1',
  last_key_tuple:[3,'LSU-SYNTHETIC',id],filter_fingerprint:'a'.repeat(64),null_order:'empty_before_text'};
const attentionCursor={version:1,query_id:'InventoryAttentionQuery',sort_registry_id:'INVENTORY_ATTENTION_CANONICAL_V1',
  last_key_tuple:[2,'warehouse_rejected_resend_required','rma',id],filter_fingerprint:'b'.repeat(64),null_order:'not applicable'};
test('Inventory Stock retains blocked identity and attention uses one as_of instant across continuation without writes',async({page})=>{
  const requests=[];const instants=[];
  await page.route('**/api/v1/inventory/**',route=>{
    requests.push(route.request().method());const url=new URL(route.request().url());expect(url.searchParams.get('limit')).toBe('200');
    if(url.pathname.endsWith('/stock'))return route.fulfill({json:{items:[{spare_part_unit_id:id,local_tracking_id:'LSU-SYNTHETIC',bom_code:'SYNTHETIC-BOM',manufacturer_serial:'SYNTHETIC-SERIAL',
      condition_token:'faulty',disposition_token:'quarantined',location_kind:'unknown',location_ref_id:null,custody_text:'Synthetic custody',active_task_allocation_id:null,
      compatibility_classification:'unknown',availability_blockers:['SYNTHETIC_QUARANTINE']}],continuation:stockCursor,exact_total:2}});
    const asOf=Number(url.searchParams.get('as_of_utc'));instants.push(asOf);
    return route.fulfill({json:{items:[{attention_id:'synthetic-attention-1',target_kind:'rma',target_id:id,attention_kind:'warehouse_rejected_resend_required',severity:'action_required',
      reason:'Synthetic terminal predecessor still has an open obligation.',next_governed_action:'Review resend'}],continuation:instants.length===1?attentionCursor:null,exact_total:2,as_of_utc:asOf}});
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

test('Inventory Back restores independent Stock and attention pages, as_of, focus and scroll with fresh owner reads',async({page})=>{
  const stockReads=[],attentionReads=[];let stockSecond=0;
  await page.route('**/api/v1/inventory/**',async route=>{
    expect(route.request().method()).toBe('GET');const url=new URL(route.request().url());
    if(url.pathname.endsWith('/stock')) {
      stockReads.push(url.search);const second=url.searchParams.has('cursor');if(second)stockSecond++;
      if(second&&stockSecond>1)await new Promise(resolve=>setTimeout(resolve,150));
      return route.fulfill({json:{items:[{spare_part_unit_id:id,local_tracking_id:'LSU-SYNTHETIC',bom_code:'SYNTHETIC-BOM',manufacturer_serial:null,
        condition_token:'faulty',disposition_token:'quarantined',location_kind:'unknown',location_ref_id:null,custody_text:'Synthetic custody',active_task_allocation_id:null,
        compatibility_classification:'unknown',availability_blockers:[stockSecond>1?'SYNTHETIC_CURRENT_BLOCKER':'SYNTHETIC_PRIOR_BLOCKER']}],continuation:second?null:stockCursor,exact_total:2}});
    }
    attentionReads.push(url.search);return route.fulfill({json:{items:[{attention_id:'synthetic-attention',target_kind:'rma',target_id:id,
      attention_kind:'warehouse_rejected_resend_required',severity:'action_required',reason:'Synthetic open obligation',next_governed_action:'Review resend'}],
      continuation:url.searchParams.has('cursor')?null:attentionCursor,exact_total:2,as_of_utc:Number(url.searchParams.get('as_of_utc'))}});
  });
  // A short supported viewport makes both scroll owners exercise overflow in
  // Chromium and Edge; the one-row fixture can fit at 900px with different fonts.
  await page.setViewportSize({width:480,height:600});await page.goto('http://127.0.0.1:4174/inventory');
  const stock=page.getByRole('region',{name:'Stock',exact:true});const attention=page.getByRole('region',{name:'Inventory Needs Attention',exact:true});
  await stock.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>stockReads.length).toBe(2);
  await attention.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>attentionReads.length).toBe(2);
  await expect(attention.getByRole('button',{name:'Next page'})).toHaveCount(0);
  const scroll=await page.evaluate(()=>{const main=document.getElementById('main-content');main.scrollTop=80;
    const table=document.querySelector('[aria-label="Stock"] .table-owner');table.scrollLeft=160;return {main:main.scrollTop,stock:table.scrollLeft};});
  expect(scroll.main).toBeGreaterThan(0);expect(scroll.stock).toBeGreaterThan(0);
  await page.getByRole('link',{name:'Objectives',exact:true}).click();await page.goBack();
  await expect(stock.getByText('Blocker: SYNTHETIC_CURRENT_BLOCKER')).toBeVisible();
  await expect(attention.getByRole('button',{name:'Refresh Inventory attention'})).toBeFocused();
  await expect(page.getByText('The previous Inventory control is unavailable; focus returned to Refresh Inventory attention.')).toBeVisible();
  expect(stockReads[2]).toBe(stockReads[1]);expect(attentionReads[2]).toBe(attentionReads[1]);
  await expect.poll(()=>page.evaluate(()=>({main:document.getElementById('main-content').scrollTop,
    stock:document.querySelector('[aria-label="Stock"] .table-owner').scrollLeft}))).toEqual(scroll);
  const raw=await page.evaluate(()=>JSON.stringify(history.state));for(const secret of ['inventoryQueries','LSU-SYNTHETIC','as_of_utc','SYNTHETIC_'])expect(raw).not.toContain(secret);
  await page.goForward();await expect(page).toHaveURL(/\/objectives$/);await page.goBack();
  await expect(stock.getByText('Blocker: SYNTHETIC_CURRENT_BLOCKER')).toBeVisible();expect(stockReads[3]).toBe(stockReads[1]);expect(attentionReads[3]).toBe(attentionReads[1]);
});

test('Inventory rejects unclosed owner continuation rather than retaining copied data as return intent',async({page})=>{
  await page.route('**/api/v1/inventory/stock?**',route=>route.fulfill({json:{items:[],exact_total:0,continuation:{body:'unapproved copied facts'}}}));
  await page.route('**/api/v1/inventory/attention?**',route=>route.fulfill({json:{items:[],exact_total:0,continuation:stockCursor,
    as_of_utc:Number(new URL(route.request().url()).searchParams.get('as_of_utc'))}}));
  await page.goto('http://127.0.0.1:4174/inventory');
  for(const name of ['Stock','Inventory Needs Attention']) {
    const region=page.getByRole('region',{name,exact:true});await expect(region.getByRole('alert')).toContainText('owner projection could not be rendered');
    await expect(region.getByRole('button',{name:'Next page'})).toHaveCount(0);
  }
});
