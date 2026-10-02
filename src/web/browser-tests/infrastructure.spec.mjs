import {test,expect} from '@playwright/test';
const id='33333333-3333-4333-8333-333333333333';
const site='44444444-4444-4444-8444-444444444444';
test('Infrastructure preserves contextual identity, explicit opening and physical/containment/cloud separation at narrow width',async({page})=>{
  let reads=0;
  await page.route('**/api/v1/infrastructure/**',route=>{
    reads++;const url=new URL(route.request().url());
    if(url.pathname.endsWith('/tree'))return route.fulfill({json:{nodes:[
      {kind:'network_element',id,label:'Synthetic NE Alpha',parent_context_id:null,lifecycle:'active',warning_codes:[]},
      {kind:'containment',id,label:'Synthetic NE Alpha containment context',parent_context_id:site,lifecycle:'active',warning_codes:[]}],next_cursor:{synthetic:'next'}}});
    if(url.pathname.endsWith('/components')){
      expect(url.searchParams.get('limit')).toBe('200');return route.fulfill({json:{items:[{installed_component_id:site,state:'removed',bom_code:'SYNTHETIC-BOM',
        manufacturer_serial:'SYNTHETIC-SERIAL',slot_label:'Synthetic slot 1',condition:'removed',device_part_unit_id:null,physical_consequence_id:null}],next_cursor:{synthetic:'components-next'}}});
    }
    if(url.pathname.endsWith('/history')){
      expect(url.searchParams.get('limit')).toBe('5');
      const text=value=>({kind:'text',text_value:value,integer_value:null,boolean_value:null,entity_ref:null});
      return route.fulfill({json:{events:[{event_id:site,event_kind:'synthetic_description_updated',recorded_at_utc:1000,effective_at_utc:null,command_id:id,
        summary:{changes:[{field:'operational_name',prior:text('Synthetic old name'),new:text('Synthetic new name')}],reason_code:null,warning_codes:[]}}],next_cursor:null}});
    }
    return route.fulfill({json:{network_element_id:id,operational_name:'Synthetic NE Alpha',revision:2,lifecycle:'active',site:{kind:'site',id:site},customer_org_id:site,
      placement:{rack_id:null,u_start:null,u_span:null,revision:1,explicit_unracked:true},model:null,cloud_deployment:{kind:'cloud_deployment',id:site},primary_ip:null,
      ip_count:0,containment_parent:{kind:'network_element',id:site},containment_child_count:0,device_reference_count:1,installed_component_count:1,
      warning_codes:['SYNTHETIC_WARNING']}});
  });
  await page.setViewportSize({width:480,height:900});await page.goto('http://127.0.0.1:4174/infrastructure');
  const rows=page.getByRole('listitem');await expect(rows).toHaveCount(2);await rows.first().click();
  await expect(page.getByRole('region',{name:'Opened Network Element'})).toHaveCount(0);
  await rows.first().press('Enter');await expect(page.getByRole('heading',{name:'Synthetic NE Alpha',exact:true})).toBeVisible();
  await expect(page.getByRole('tab')).toHaveText(['Summary','Placement','Components','IP Addresses','Relationships','History','Workbook Activity']);
  await page.getByRole('tab',{name:'Placement',exact:true}).click();await expect(page.getByText('Explicitly Unracked', {exact:true})).toBeVisible();
  await page.getByRole('tab',{name:'Relationships',exact:true}).click();await expect(page.getByRole('heading',{name:'Containment',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Cloud assignment',exact:true})).toBeVisible();
  await page.getByRole('tab',{name:'IP Addresses',exact:true}).click();await expect(page.getByRole('heading',{name:'Descriptive IP inventory'})).toBeVisible();
  await expect(page.getByText('No automatic primary promotion is implied.',{exact:false})).toBeVisible();
  await page.getByRole('tab',{name:'Components',exact:true}).click();await expect(page.locator('tbody tr').filter({hasText:'SYNTHETIC-SERIAL'})).toHaveCount(1);
  await expect(page.getByRole('button',{name:'Next page'})).toBeVisible();expect(reads).toBe(4);
  await page.getByRole('tab',{name:'History',exact:true}).click();await expect(page.getByText('operational_name: Synthetic old name → Synthetic new name')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Infrastructure oversized owner explorer is rejected with bounded error',async({page})=>{
  await page.route('**/api/v1/infrastructure/tree?**',route=>route.fulfill({json:{nodes:Array.from({length:201},()=>({kind:'network_element',id,label:'Synthetic row',parent_context_id:null,lifecycle:'active',warning_codes:[]})),next_cursor:null}}));
  await page.goto('http://127.0.0.1:4174/infrastructure');await expect(page.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(page.getByRole('listitem')).toHaveCount(0);
});
