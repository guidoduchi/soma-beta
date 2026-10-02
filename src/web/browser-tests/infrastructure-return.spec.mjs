import {test,expect} from '@playwright/test';
const id='33333333-3333-4333-8333-333333333333';
const other='44444444-4444-4444-8444-444444444444';
const cursor=(query,key,null_order='NOT_APPLICABLE')=>({version:1,query_id:query,sort_registry_id:query+'_ORDER_V1',last_key_tuple:key,filter_fingerprint:'a'.repeat(64),null_order});
const explorerCursor=cursor('InfrastructureExplorerQuery',[other,other,4,id],'NULLS_LAST');
const componentCursor=cursor('InstalledComponentQuery',[null,other],'NULLS_LAST');
const historyCursor=cursor('InfrastructureHistoryQuery',[100,other]);
const node=(value,label)=>({kind:'network_element',id:value,label,parent_context_id:null,lifecycle:'active',warning_codes:[]});
const detail=warning=>({network_element_id:id,operational_name:'Synthetic return NE',revision:2,lifecycle:'active',site:{kind:'site',id:other},customer_org_id:other,
  placement:{rack_id:null,u_start:null,u_span:null,revision:1,explicit_unracked:true},model:null,cloud_deployment:null,primary_ip:null,ip_count:0,
  containment_parent:null,containment_child_count:0,device_reference_count:0,installed_component_count:1,warning_codes:warning?[warning]:[]});
const component={installed_component_id:other,state:'removed',bom_code:'SYNTHETIC-BOM',manufacturer_serial:'SYNTHETIC-SECOND-PAGE',slot_label:null,
  condition:'removed',device_part_unit_id:null,physical_consequence_id:null};
test('Infrastructure Back refetches the exact explorer/component/history pages and restores opened identity, tab, focus and scroll',async({page})=>{
  const reads={tree:[],components:[],history:[]};let changed=false;
  await page.route('**/api/v1/objectives?**',route=>route.fulfill({json:{items:[],exact_total:0,continuation:null,as_of_utc:Number(new URL(route.request().url()).searchParams.get('as_of_utc'))}}));
  await page.route('**/api/v1/infrastructure/**',route=>{
    const url=new URL(route.request().url());const continuation=url.searchParams.has('cursor');
    if(url.pathname.endsWith('/tree')) {
      reads.tree.push(url.search);if(continuation)expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(explorerCursor);
      return route.fulfill({json:{nodes:[node(id,'Synthetic return NE'),...Array.from({length:15},(_,index)=>node(`${(index+1).toString(16).padStart(8,'0')}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`,'Synthetic context '+index))],next_cursor:continuation?null:explorerCursor}});
    }
    if(url.pathname.endsWith('/components')) {
      reads.components.push(url.search);if(continuation)expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(componentCursor);
      return route.fulfill({json:{items:continuation?[component]:[],next_cursor:continuation?null:componentCursor}});
    }
    if(url.pathname.endsWith('/history')) {
      reads.history.push(url.search);if(continuation)expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(historyCursor);
      return route.fulfill({json:{events:[],next_cursor:continuation?null:historyCursor}});
    }
    return route.fulfill({json:detail(changed?'SYNTHETIC_CURRENT_OWNER_WARNING':null)});
  });
  await page.goto('http://127.0.0.1:4174/infrastructure');await page.getByRole('button',{name:'Next explorer page'}).click();
  await page.getByRole('listitem').first().press('Enter');await page.getByRole('tab',{name:'Components',exact:true}).click();
  await page.getByRole('button',{name:'Next page',exact:true}).click();await expect(page.getByText('SYNTHETIC-SECOND-PAGE',{exact:true})).toBeVisible();
  await page.getByRole('tab',{name:'History',exact:true}).click();await page.getByRole('button',{name:'Next page',exact:true}).click();
  await page.getByRole('tab',{name:'Components',exact:true}).click();
  const offsets=await page.evaluate(()=>{
    const explorer=document.querySelector('[data-return-scroll="explorer"]');explorer.scrollTop=140;
    const table=document.querySelector('[data-return-scroll="components"]');table.scrollLeft=90;
    return {explorer:explorer.scrollTop,components:table.scrollLeft};
  });
  expect(offsets.explorer).toBeGreaterThan(0);expect(offsets.components).toBeGreaterThan(0);
  await page.getByRole('link',{name:'Objectives',exact:true}).click();changed=true;await page.goBack();
  await expect(page.getByRole('tab',{name:'Components',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByText('SYNTHETIC-SECOND-PAGE',{exact:true})).toBeVisible();await expect(page.getByText('SYNTHETIC_CURRENT_OWNER_WARNING',{exact:true})).toBeVisible();
  await expect(page.getByRole('tab',{name:'Components',exact:true})).toBeFocused();
  await expect.poll(()=>page.evaluate(()=>document.querySelector('[data-return-scroll="explorer"]').scrollTop)).toBe(offsets.explorer);
  await expect.poll(()=>page.evaluate(()=>document.querySelector('[data-return-scroll="components"]').scrollLeft)).toBe(offsets.components);
  expect(reads.tree.at(-1)).toBe(reads.tree[1]);expect(reads.components.at(-1)).toBe(reads.components[1]);expect(reads.history.at(-1)).toBe(reads.history[1]);
  expect(JSON.stringify(await page.evaluate(()=>history.state))).not.toContain('SYNTHETIC');
  await page.goForward();await expect(page).toHaveURL(/\/objectives$/);await page.goBack();
  await expect(page.getByRole('tab',{name:'Components',exact:true})).toHaveAttribute('aria-selected','true');
});
test('Infrastructure return selects the nearest surviving row and focuses its deterministic fallback without opening it',async({page})=>{
  let removed=false;
  await page.route('**/api/v1/objectives?**',route=>route.fulfill({json:{items:[],exact_total:0,continuation:null,as_of_utc:Number(new URL(route.request().url()).searchParams.get('as_of_utc'))}}));
  await page.route('**/api/v1/infrastructure/tree?**',route=>route.fulfill({json:{nodes:removed?[node(other,'Synthetic surviving row')]:[node(id,'Synthetic removed row'),node(other,'Synthetic surviving row')],next_cursor:removed?null:explorerCursor}}));
  await page.goto('http://127.0.0.1:4174/infrastructure');await page.getByRole('listitem').first().click();await page.getByRole('button',{name:'Next explorer page'}).focus();
  await page.getByRole('link',{name:'Objectives',exact:true}).click();removed=true;await page.goBack();
  const row=page.getByRole('listitem');await expect(row).toHaveAttribute('aria-current','true');await expect(row).toBeFocused();
  await expect(page.getByRole('region',{name:'Opened Network Element'})).toHaveCount(0);
  await expect(page.getByText('The previous Infrastructure control is unavailable; focus returned to the nearest row or Refresh explorer.')).toBeVisible();
});
