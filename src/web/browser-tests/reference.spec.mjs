import {test,expect} from '@playwright/test';
const contact='11111111-1111-4111-8111-111111111111';
const dispatch='22222222-2222-4222-8222-222222222222';
const customer='33333333-3333-4333-8333-333333333333';
const definitions={'contacts':['contact',contact,'Synthetic Contact'],'dispatch-locations':['dispatch_location',dispatch,'Synthetic Location'],
  'customer-organizations':['customer_organization',customer,'Synthetic Customer']};
function list(resource){const [kind,id,name]=definitions[resource];return {items:[{reference_type:kind,reference_id:id,display_name:name,revision:1,lifecycle_state:'active'}],continuation:null};}
test.beforeEach(async({page})=>{
  await page.route(/\/api\/v1\/(?:product-lines|contracts|contract-product-lines|sla\/classification-mappings)\?/,route=>route.fulfill({json:{items:[],continuation:null}}));
});

test('Settings uses bounded owner reference pages and explicit detail; channel text stays inert with archived paging',async({page})=>{
  const requests=[];
  await page.route('**/api/v1/reference/**',route=>{
    const url=new URL(route.request().url());requests.push({url,method:route.request().method()});const parts=url.pathname.split('/');const resource=parts[4];
    if(parts.length===5){expect(url.searchParams.get('limit')).toBe('200');return route.fulfill({json:list(resource)});}
    if(url.pathname.endsWith('/channels'))return route.fulfill({json:{items:[{contact_channel_id:'synthetic-channel',channel_kind:'email',
      value_text:'<img src=x onerror="window.syntheticInjected=true">',lifecycle_state:url.searchParams.get('include_archived')==='true'?'archived':'active',revision:1}],
      continuation:{version:1,query_id:'GetContactChannels',sort_registry_id:'CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1',last_key_tuple:['email',1,contact],filter_fingerprint:'a'.repeat(64),null_order:'not_applicable'},exact_count:2}});
    return route.fulfill({json:{reference_type:'contact',reference_id:contact,revision:1,lifecycle_state:'active',
      projection:{name:'Synthetic Contact',current_affiliation:null,active_channel_count:2}}});
  });
  await page.setViewportSize({width:480,height:900});await page.goto('http://127.0.0.1:4174/settings');
  await expect(page.getByRole('button',{name:'Open Synthetic Contact'})).toBeVisible();expect(requests.length).toBe(3);
  await page.getByRole('button',{name:'Open Synthetic Contact'}).click();
  await expect(page.getByText('Current Customer affiliation: Unbound.')).toBeVisible();
  await expect(page.getByText('<img src=x onerror="window.syntheticInjected=true">',{exact:true})).toBeAttached();
  expect(await page.evaluate(()=>window.syntheticInjected)).toBeUndefined();await expect(page.locator('img')).toHaveCount(0);
  const channels=page.getByRole('region',{name:'Contact channels'});
  await channels.getByRole('checkbox',{name:'Include archived channels'}).check();await expect(channels.getByText('Lifecycle: archived')).toBeAttached();
  await channels.getByRole('button',{name:'Next page'}).click();
  await expect.poll(()=>requests.at(-1).url.searchParams.get('cursor')).toBe(JSON.stringify({version:1,query_id:'GetContactChannels',sort_registry_id:'CONTACT_CHANNEL_KIND_CREATED_ID_ASC_V1',last_key_tuple:['email',1,contact],filter_fingerprint:'a'.repeat(64),null_order:'not_applicable'}));
  expect(requests.every(request=>request.method==='GET')).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('Settings preserves unavailable Site address and lazily loads exact owner Account Code history',async({page})=>{
  let historyReads=0;
  await page.route('**/api/v1/reference/**',route=>{
    const url=new URL(route.request().url());const parts=url.pathname.split('/');
    if(parts.length===5)return route.fulfill({json:list(parts[4])});
    if(url.pathname.endsWith('/history')){historyReads++;return route.fulfill({json:{items:[{customer_org_identifier_id:'synthetic-claim',value_text:'SYNTHETIC-SHARED',
      lifecycle_state:'superseded',created_at_utc:1,superseded_at_utc:2}],continuation:null,exact_count:1}});}
    if(parts[4]==='dispatch-locations')return route.fulfill({json:{reference_type:'dispatch_location',reference_id:dispatch,revision:1,lifecycle_state:'active',
      projection:{name:'Synthetic Location',current_address:{source:'SITE',state:'UNAVAILABLE',address_text:null,site_id:null}}}});
    return route.fulfill({json:{reference_type:'customer_organization',reference_id:customer,revision:1,lifecycle_state:'active',
      projection:{name:'Synthetic Customer',current_account_code:null,account_code_history_count:1}}});
  });
  await page.goto('http://127.0.0.1:4174/settings');await page.getByRole('button',{name:'Open Synthetic Location'}).click();
  await expect(page.getByText('Current address source: Site-derived.')).toBeVisible();
  await expect(page.getByText('Current address: Unavailable from the address owner.')).toBeVisible();
  await page.getByRole('button',{name:'Open Synthetic Customer'}).click();await expect(page.getByText('Current Account Code claim: None.')).toBeAttached();
  expect(historyReads).toBe(0);await page.getByRole('button',{name:'Show Account Code history'}).click();
  await expect(page.getByText('SYNTHETIC-SHARED',{exact:true})).toBeAttached();expect(historyReads).toBe(1);
});

test('Settings rejects missing affiliation facts instead of inventing Unbound context',async({page})=>{
  await page.route('**/api/v1/reference/**',route=>{
    const parts=new URL(route.request().url()).pathname.split('/');
    return route.fulfill({json:parts.length===5?list(parts[4]):{reference_type:'contact',reference_id:contact,revision:1,lifecycle_state:'active',projection:{name:'Synthetic Contact',active_channel_count:0}}});
  });
  await page.goto('http://127.0.0.1:4174/settings');await page.getByRole('button',{name:'Open Synthetic Contact'}).click();
  await expect(page.getByRole('region',{name:'Contacts',exact:true}).getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(page.getByText('Current Customer affiliation: Unbound.')).toHaveCount(0);
});
