import {test,expect} from '@playwright/test';
const product='11111111-1111-4111-8111-111111111111',contract='22222222-2222-4222-8222-222222222222',cpl='33333333-3333-4333-8333-333333333333';
test.beforeEach(async({page})=>{await page.route('**/api/v1/reference/**',route=>route.fulfill({json:{items:[],continuation:null}}));});
test('Settings preserves reusable Product Line versus customer Contract and current CPL policy with opaque continuation',async({page})=>{
  const requests=[];
  await page.route(/\/api\/v1\/(?:product-lines|contracts|contract-product-lines|sla\/classification-mappings)\?/,route=>{
    const url=new URL(route.request().url());requests.push({url,method:route.request().method()});expect(url.searchParams.get('limit')).toBe('200');
    const state={lifecycle_state:'active',revision:1};let items=[];
    if(url.pathname==='/api/v1/product-lines')items=[{...state,product_line_id:product,name:'Synthetic Reusable Product'}];
    if(url.pathname==='/api/v1/contracts')items=[{...state,contract_id:contract,customer_org_id:'synthetic-customer',name:'Synthetic Contract',contract_reference:'SYNTHETIC-CT'}];
    if(url.pathname==='/api/v1/contract-product-lines')items=[{...state,contract_product_line_id:cpl,contract_id:contract,product_line_id:product,
      customer_org_id:'synthetic-customer',contract_reference:'SYNTHETIC-CT',product_line_name:'Synthetic Reusable Product',current_policy_revision_id:'synthetic-policy-2',
      policy_name:'Synthetic Current Policy',policy_revision_ordinal:2}];
    return route.fulfill({json:{items,continuation:url.pathname==='/api/v1/product-lines'&&!url.searchParams.has('cursor')?{synthetic:['name',product]}:null}});
  });
  await page.setViewportSize({width:480,height:900});await page.goto('http://127.0.0.1:4174/settings');
  const products=page.getByRole('region',{name:'Product Lines',exact:true});const cpls=page.getByRole('region',{name:'Contract Product Lines',exact:true});
  await expect(products.getByText('Synthetic Reusable Product',{exact:true})).toBeAttached();
  await expect(cpls.getByText('Current policy:',{exact:false})).toContainText('Synthetic Current Policy / synthetic-policy-2; ordinal 2');
  await expect(products.getByText('Current policy:',{exact:false})).toHaveCount(0);
  await products.getByRole('button',{name:'Next page'}).click();
  await expect.poll(()=>requests.at(-1).url.searchParams.get('cursor')).toBe(JSON.stringify({synthetic:['name',product]}));
  expect(requests.every(request=>request.method==='GET')).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Settings rejects missing current-policy facts and unknown collection identity without fabricating policyless state',async({page})=>{
  await page.route(/\/api\/v1\/(?:product-lines|contracts|contract-product-lines|sla\/classification-mappings)\?/,route=>{
    const url=new URL(route.request().url());const state={lifecycle_state:'active',revision:1};
    const items=url.pathname==='/api/v1/contract-product-lines'?[{...state,contract_product_line_id:cpl,product_line_name:'Synthetic Missing Policy'}]
      :url.pathname==='/api/v1/product-lines'?[{...state,name:'Synthetic Missing Identity'}]:[];
    return route.fulfill({json:{items,continuation:null}});
  });
  await page.goto('http://127.0.0.1:4174/settings');
  for(const name of ['Product Lines','Contract Product Lines']) {
    await expect(page.getByRole('region',{name,exact:true}).getByRole('alert')).toContainText('owner projection could not be rendered');
  }
  await expect(page.getByText('No current policy revision')).toHaveCount(0);
});
