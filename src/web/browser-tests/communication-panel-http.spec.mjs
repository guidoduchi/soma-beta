import {test,expect} from '@playwright/test';
const id='33333333-3333-4333-8333-333333333333';
const message='44444444-4444-4444-8444-444444444444';
const continuation={version:1,query_id:'ListCommunications',sort_registry_id:'ListCommunications_ORDER_V1',
  last_key_tuple:[0,null,message],filter_fingerprint:'a'.repeat(64),null_order:'chronology null last'};
const chronology={known:false,utc_epoch_seconds:null,source_kind:'UNKNOWN'};
const projection=(type,terminal=false)=>({summary:{target_type:type,target_id:id,received_count:0,sent_count:0,unknown_count:1,
  last_interaction:chronology,last_direction:'UNKNOWN',pending_proposals:0,coverage_state:'UNKNOWN',warnings:['COMM_COVERAGE_INCOMPLETE'],body_navigation_available:!terminal},
  recent_messages:{items:[{communication_id:message,subject:'Synthetic canonical subject',direction:'UNKNOWN',content_state:'RETAINED',chronology}],next_cursor:terminal?null:continuation},
  terminal_frozen:terminal,warnings:terminal?['COMM_TERMINAL_FROZEN']:[]});
async function owners(page) {
  await page.route('**/api/v1/tickets/**',route=>route.fulfill({json:route.request().url().includes('/rfcs/')?
    {rfc_id:id,rfc_no:'NC00000000000001',revision:1,hierarchy_role:'root',local_archive_state:'active',direct_service_request_count:0,device_reference_count:0,subordinate_count:0,warnings:[]}:
    {service_request_id:id,identity:{official_sr_no:'C0000001',local_sr_no:null},revision:1,linked_root_rfc_count:0,device_reference_count:0,warnings:[]}}));
}
for(const [routePart,type] of [['sr','SERVICE_REQUEST'],['rfc','RFC']])test(`${type} workbench consumes exact owner panel route and full cursor without client composition`,async({page})=>{
  const paths=[];
  await owners(page);
  await page.route('**/api/v1/communications/**',route=>{
    const url=new URL(route.request().url());paths.push(url.pathname);expect(route.request().method()).toBe('GET');
    if(url.pathname==='/api/v1/communications/messages/'+message)return route.fulfill({json:{communication_id:message,subject:'Synthetic body subject',
      body:'<script>window.syntheticUnsafe=true</script>',body_kind:'PLAIN_TEXT',content_state:'RETAINED'}});
    expect(url.pathname).toBe(`/api/v1/communications/entities/${type}/${id}/panel`);expect(url.searchParams.get('limit')).toBe('50');
    if(url.searchParams.has('cursor')) {
      expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(continuation);
      return route.fulfill({json:{...projection(type),recent_messages:{items:[],next_cursor:null}}});
    }
    return route.fulfill({json:projection(type)});
  });
  await page.goto(`http://127.0.0.1:4174/tickets/${routePart}/${id}`);
  const panel=page.getByRole('region',{name:'Canonical communication evidence'});
  await expect(panel).toContainText('Synthetic canonical subject');await expect(panel).toContainText('COMM_COVERAGE_INCOMPLETE');
  await panel.getByRole('button',{name:'Open canonical message'}).click();
  const detail=page.getByRole('region',{name:'Canonical message detail'});
  await expect(detail).toContainText('<script>window.syntheticUnsafe=true</script>');
  expect(await page.evaluate(()=>window.syntheticUnsafe)).toBeUndefined();
  await detail.getByRole('button',{name:'Close message'}).click();
  await panel.getByRole('button',{name:'Next messages'}).click();await expect(panel).toContainText('No linked messages in this page');
  expect(paths).toEqual([`/api/v1/communications/entities/${type}/${id}/panel`,'/api/v1/communications/messages/'+message,
    `/api/v1/communications/entities/${type}/${id}/panel`]);
});
test('Terminal owner panel is readable at narrow width without body navigation',async({page})=>{
  await owners(page);await page.route('**/api/v1/communications/**',route=>route.fulfill({json:projection('SERVICE_REQUEST',true)}));
  await page.setViewportSize({width:480,height:900});await page.goto(`http://127.0.0.1:4174/tickets/sr/${id}`);
  await page.getByRole('button',{name:'Communications',exact:true}).click();
  const panel=page.getByRole('region',{name:'Canonical communication evidence'});
  await expect(panel).toContainText('Historical terminal summary');await expect(panel).toContainText('COMM_TERMINAL_FROZEN');
  await expect(panel.getByRole('button',{name:'Open canonical message'})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Panel transport failure keeps the independent operational owner workbench usable',async({page})=>{
  await owners(page);await page.route('**/api/v1/communications/**',route=>route.fulfill({status:401,json:{code:'AUTH_SESSION_INVALID'}}));
  await page.goto(`http://127.0.0.1:4174/tickets/sr/${id}`);
  await expect(page.getByRole('heading',{name:'Service Request C0000001'})).toBeVisible();
  const panel=page.getByRole('region',{name:'Canonical communication evidence'});
  await expect(panel.getByRole('alert')).toContainText('Communication evidence is unavailable');
  await expect(panel.getByRole('button',{name:'Retry communications'})).toBeVisible();
  await page.getByRole('tab',{name:'Devices',exact:true}).click();await expect(page.getByRole('heading',{name:'Devices',exact:true})).toBeVisible();
});
