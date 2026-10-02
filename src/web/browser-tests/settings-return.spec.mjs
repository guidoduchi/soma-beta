import {test,expect} from '@playwright/test';
const contact='11111111-1111-4111-8111-111111111111',customer='22222222-2222-4222-8222-222222222222',product='33333333-3333-4333-8333-333333333333';
const cursor=(query,sort,key,nullOrder='none')=>({version:1,query_id:query,sort_registry_id:sort,last_key_tuple:key,filter_fingerprint:'a'.repeat(64),null_order:nullOrder});
const channelCursor=cursor('GetContactChannels','CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1',['email',1,contact],'not_applicable');
const productCursor=cursor('ListProductLines','PRODUCT_LINE_PRESENTATION_ASC_V1',['synthetic',product]);

test('Settings Back restores independent owner pages, opened references, archived channels and Account Code disclosure with fresh facts',async({page})=>{
  let fresh=false;const reads=[];
  await page.route('**/api/v1/**',async route=>{
    const url=new URL(route.request().url());reads.push(url);const path=url.pathname;
    if(path.endsWith('/channels'))return route.fulfill({json:{items:Array.from({length:20},(_,i)=>({contact_channel_id:'synthetic-channel-'+i,channel_kind:'email',value_text:(fresh?'Fresh':'Initial')+' channel '+i+' '+'.'.repeat(120),lifecycle_state:'archived',revision:1})),continuation:channelCursor}});
    if(path.endsWith('/history'))return route.fulfill({json:{items:[],continuation:null,exact_count:0}});
    if(path===`/api/v1/reference/contacts/${contact}`)return route.fulfill({json:{reference_type:'contact',reference_id:contact,revision:fresh?2:1,lifecycle_state:'active',projection:{name:'Synthetic Contact',current_affiliation:null,active_channel_count:20}}});
    if(path===`/api/v1/reference/customer-organizations/${customer}`)return route.fulfill({json:{reference_type:'customer_organization',reference_id:customer,revision:1,lifecycle_state:'active',projection:{name:'Synthetic Customer',current_account_code:null,account_code_history_count:0}}});
    if(path==='/api/v1/reference/contacts'||path==='/api/v1/reference/customer-organizations'){const isContact=path.endsWith('/contacts');return route.fulfill({json:{items:[{reference_type:isContact?'contact':'customer_organization',reference_id:isContact?contact:customer,display_name:isContact?'Synthetic Contact':'Synthetic Customer',lifecycle_state:'active',revision:1}],continuation:null}});}
    if(path==='/api/v1/product-lines')return route.fulfill({json:{items:[{product_line_id:product,name:fresh?'Fresh Product':'Initial Product',lifecycle_state:'active',revision:fresh?2:1}],continuation:productCursor}});
    return route.fulfill({json:{items:[],continuation:null}});
  });
  await page.setViewportSize({width:480,height:600});await page.goto('http://127.0.0.1:4174/settings');
  await page.getByRole('button',{name:'Open Synthetic Customer'}).click();await page.getByRole('button',{name:'Show Account Code history'}).click();
  await page.getByRole('button',{name:'Open Synthetic Contact'}).click();const channels=page.getByRole('region',{name:'Contact channels'});
  await channels.getByRole('checkbox').check();await channels.getByRole('button',{name:'Next page'}).click();
  await page.getByRole('region',{name:'Product Lines',exact:true}).getByRole('button',{name:'Next page'}).click();
  await expect.poll(()=>reads.some(url=>url.pathname==='/api/v1/product-lines'&&url.searchParams.get('cursor')===JSON.stringify(productCursor))).toBe(true);
  await channels.getByRole('checkbox').focus();
  const saved=await page.evaluate(()=>{const main=document.getElementById('main-content'),pane=document.querySelector('[data-return-scroll="channels"]');main.scrollTop=200;pane.scrollTop=80;pane.scrollLeft=25;return [main.scrollTop,pane.scrollTop,pane.scrollLeft];});
  expect(saved[0]).toBeGreaterThan(0);expect(saved[2]).toBeGreaterThan(0);await page.getByRole('link',{name:'Tickets',exact:true}).click();fresh=true;reads.length=0;await page.goBack();
  await expect(page.getByRole('button',{name:'Hide Account Code history'})).toBeAttached();await expect(channels.getByRole('checkbox')).toBeChecked();
  await expect(channels.getByText('Fresh channel 0',{exact:false})).toBeAttached();await expect(page.getByText('Fresh Product',{exact:true})).toBeAttached();
  await expect(channels.getByRole('checkbox')).toBeFocused();
  for(const [path,expected] of [['/api/v1/product-lines',productCursor],[`/api/v1/reference/contacts/${contact}/channels`,channelCursor]]){
    const returned=reads.find(url=>url.pathname===path);expect(JSON.parse(returned.searchParams.get('cursor'))).toEqual(expected);
  }
  await expect.poll(()=>page.evaluate(()=>{const pane=document.querySelector('[data-return-scroll="channels"]');return [document.getElementById('main-content').scrollTop,pane.scrollTop,pane.scrollLeft];})).toEqual(saved);
  expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('queries');expect(await page.evaluate(()=>JSON.stringify(history.state))).not.toContain('Fresh');
});

test('Settings Back explains a missing paging control and restores focus to Settings',async({page})=>{
  let fresh=false;
  await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;return route.fulfill({json:{items:path==='/api/v1/product-lines'?[{product_line_id:product,name:'Synthetic Product',lifecycle_state:'active',revision:1}]:[],continuation:path==='/api/v1/product-lines'&&!fresh?productCursor:null}});});
  await page.goto('http://127.0.0.1:4174/settings');await page.getByRole('region',{name:'Product Lines',exact:true}).getByRole('button',{name:'Next page'}).focus();
  await page.getByRole('link',{name:'Tickets',exact:true}).click();fresh=true;await page.goBack();
  await expect(page.getByRole('status').filter({hasText:'previous Settings control is unavailable'})).toBeVisible();
  await expect(page.locator('#main-content')).toBeFocused();
});

test('Communication Settings Back retains source coverage and complete job cursor, then refetches owner progress',async({page})=>{
  let fresh=false;const reads=[];const jobCursor=cursor('ListCommunicationJobs','ListCommunicationJobs_ORDER_V1',[1,contact]);
  await page.route('**/api/v1/**',route=>{const url=new URL(route.request().url());reads.push(url);const path=url.pathname;
    if(path.endsWith('/source-scopes'))return route.fulfill({json:{items:[{source_scope_id:contact,revision:1,display_name:'Synthetic Scope',health_state:'PARTIAL',processing_enabled:true,selected_folders:[]}],next_cursor:null}});
    if(path.endsWith('/coverage'))return route.fulfill({json:{source_scope_id:contact,folders:[],warnings:[fresh?'SYNTHETIC_FRESH_COVERAGE':'SYNTHETIC_INITIAL_COVERAGE']}});
    if(path.endsWith('/jobs'))return route.fulfill({json:{items:[{job_id:contact,source_scope_id:contact,job_kind:'ORDINARY',state:'RUNNING',phase:null,percentage:null,diagnostic_code:null,counters:{discovered:fresh?9:1,inspected:0,matched:0,retained:0,unchanged:0,proposed:0,skipped:0,warnings:0,failures:0,estimated_total:null}}],next_cursor:jobCursor}});
    return route.fulfill({json:{items:[],next_cursor:null}});
  });
  await page.goto('http://127.0.0.1:4174/settings/communications');await page.getByRole('button',{name:'View coverage for Synthetic Scope'}).click();
  const jobs=page.getByRole('region',{name:'Communication Jobs'});await jobs.getByRole('button',{name:'Next page'}).click();
  await expect.poll(()=>reads.some(url=>url.pathname.endsWith('/jobs')&&url.searchParams.has('cursor'))).toBe(true);
  await page.getByRole('button',{name:'View coverage for Synthetic Scope'}).focus();await page.getByRole('link',{name:'Tickets',exact:true}).click();fresh=true;reads.length=0;await page.goBack();
  await expect(page.getByText('SYNTHETIC_FRESH_COVERAGE',{exact:true})).toBeAttached();await expect(jobs.getByText('discovered: 9',{exact:true})).toBeAttached();
  await expect(page.getByRole('button',{name:'View coverage for Synthetic Scope'})).toBeFocused();expect(JSON.parse(reads.find(url=>url.pathname.endsWith('/jobs')).searchParams.get('cursor'))).toEqual(jobCursor);
});

test('Appearance Back restores logical focus after querying changed accepted preferences',async({page})=>{
  let fresh=false;
  await page.route('**/api/v1/settings/ui.*',route=>{const key=new URL(route.request().url()).pathname.split('/').at(-1);return route.fulfill({json:{setting_key:key,
    value:key==='ui.skin_id'?'soma_core':fresh?'dark':'light',revision:fresh?2:1,source:'PERSISTED',contract_name:key+'.v1',contract_version:1,semantic_owner:'LLD-10'}});});
  await page.goto('http://127.0.0.1:4174/settings/appearance');const refresh=page.getByRole('button',{name:'Refresh appearance'});
  await expect(page.getByLabel('Color mode')).toHaveValue('light');await refresh.focus();await page.getByRole('link',{name:'Tickets',exact:true}).click();fresh=true;await page.goBack();
  await expect(page.getByLabel('Color mode')).toHaveValue('dark');await expect(refresh).toBeFocused();await expect(page.locator('html')).toHaveAttribute('data-mode','dark');
  await expect(page.getByLabel('Color mode')).toBeDisabled();
});

test('Settings rejects an unclosed owner continuation before exposing paging or return navigation',async({page})=>{
  await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;return route.fulfill({json:{items:path==='/api/v1/product-lines'?[{product_line_id:product,name:'Synthetic Product',lifecycle_state:'active',revision:1}]:[],continuation:path==='/api/v1/product-lines'?{...productCursor,last_key_tuple:['truncated']}:null}});});
  await page.goto('http://127.0.0.1:4174/settings');const products=page.getByRole('region',{name:'Product Lines',exact:true});
  await expect(products.getByRole('alert')).toContainText('owner projection could not be rendered');await expect(products.getByRole('button',{name:'Next page'})).toHaveCount(0);
  await expect(page.getByRole('region',{name:'Customer Contracts',exact:true}).getByText('0 owner catalog records',{exact:false})).toBeVisible();
});

test('Settings rejects malformed owner identity before exposing an Open action',async({page})=>{
  await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;return route.fulfill({json:{items:path==='/api/v1/reference/contacts'?[{reference_type:'contact',reference_id:'invalid',display_name:'Synthetic Invalid Contact',lifecycle_state:'active',revision:1}]:[],continuation:null}});});
  await page.goto('http://127.0.0.1:4174/settings');const contacts=page.getByRole('region',{name:'Contacts',exact:true});
  await expect(contacts.getByRole('alert')).toContainText('owner projection could not be rendered');await expect(page.getByRole('button',{name:'Open Synthetic Invalid Contact'})).toHaveCount(0);
});
