import {test,expect} from '@playwright/test';
const scope='11111111-1111-4111-8111-111111111111';
const settings={processing_enabled:['COMM_PROCESSING_ENABLED_V1',false],processing_interval_minutes:['COMM_PROCESSING_INTERVAL_V1',60],
  overlap_messages:['COMM_OVERLAP_MESSAGES_V1',50],orphan_grace_minutes:['COMM_ORPHAN_GRACE_V1',10080],auto_backfill_max_days:['COMM_AUTO_BACKFILL_DAYS_V1',7]};
const counters={discovered:4,inspected:3,matched:1,retained:1,unchanged:0,proposed:0,skipped:2,warnings:1,failures:0,estimated_total:null};
async function mockSettings(page){await page.route('**/api/v1/settings/communications.*',route=>{
  const key=new URL(route.request().url()).pathname.split('/').at(-1);const [contract,value]=settings[key.split('.').at(-1)];
  return route.fulfill({json:{setting_key:key,value,revision:null,source:'DEFAULT',contract_name:contract,contract_version:1,semantic_owner:'LLD-09'}});
});}
test('Communications Settings consumes bounded scopes, coverage, exact jobs and bodyless housekeeping through reads only',async({page})=>{
  await mockSettings(page);const requests=[];const jobPages=[];
  await page.route('**/api/v1/communications/**',route=>{
    const url=new URL(route.request().url());requests.push({url,method:route.request().method()});
    if(url.pathname.endsWith('/source-scopes')){expect(url.searchParams.get('limit')).toBe('8');return route.fulfill({json:{items:[{
      source_scope_id:scope,revision:1,display_name:'Synthetic Scope',health_state:'PARTIAL',processing_enabled:false,
      selected_folders:[{folder_key:'synthetic-inbox',role:'INBOX',display_name:'Synthetic Inbox'}]}],next_cursor:null}});}
    if(url.pathname.endsWith('/coverage'))return route.fulfill({json:{source_scope_id:scope,warnings:['COMM_COVERAGE_INCOMPLETE'],folders:[{
      source_scope_id:scope,folder_key:'synthetic-inbox',forward_state:'UNKNOWN',historical_state:'BOUNDED_COMPLETE',high_water:null,warnings:['COMM_COVERAGE_INCOMPLETE']}]}});
    expect(url.searchParams.get('limit')).toBe('100');
    if(url.pathname.endsWith('/jobs')){jobPages.push(url);return route.fulfill({json:{items:[{job_id:'synthetic-job',source_scope_id:scope,job_kind:'ORDINARY',
      state:'RUNNING',phase:null,counters,percentage:null,diagnostic_code:null}],next_cursor:jobPages.length===1?{version:1,query_id:'ListCommunicationJobs',sort_registry_id:'ListCommunicationJobs_ORDER_V1',last_key_tuple:[0,scope],filter_fingerprint:'a'.repeat(64),null_order:'none'}:null}});}
    return route.fulfill({json:{items:[{communication_id:'synthetic-purged',state:'PURGED',purge_due_utc:null,reason_code:'SYNTHETIC_PURGE',protected_dependency_count:0}],next_cursor:null}});
  });
  await page.setViewportSize({width:480,height:900});await page.goto('http://127.0.0.1:4174/settings/communications');
  await expect(page.getByText('Automatic processing enabled: false.',{exact:false})).toContainText('Source: DEFAULT');
  await expect(page.getByText('Orphan grace in whole minutes: 10080.',{exact:false})).toBeAttached();
  const jobs=page.getByRole('region',{name:'Communication Jobs'});await expect(jobs.getByText('Estimated total: Unknown')).toBeAttached();
  await expect(jobs.getByText('Percentage unavailable; progress uses exact counts')).toBeAttached();await expect(jobs.getByText('0%',{exact:false})).toHaveCount(0);
  await page.getByRole('button',{name:'View coverage for Synthetic Scope'}).click();
  const coverage=page.getByRole('region',{name:'Selected Source coverage'});await expect(coverage.getByText('Forward coverage: UNKNOWN')).toBeAttached();
  await expect(coverage.getByText('Historical coverage: BOUNDED_COMPLETE')).toBeAttached();
  await expect(page.getByText('Message content is unavailable')).toBeAttached();await expect(page.getByText('Purge due (UTC): Unknown')).toBeAttached();
  await jobs.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>jobPages.length).toBe(2);
  expect(jobPages[1].searchParams.get('cursor')).toBe(JSON.stringify({version:1,query_id:'ListCommunicationJobs',sort_registry_id:'ListCommunicationJobs_ORDER_V1',last_key_tuple:[0,scope],filter_fingerprint:'a'.repeat(64),null_order:'none'}));expect(requests.every(request=>request.method==='GET')).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('Communications Settings rejects unsupported progress percentage with unknown estimated total',async({page})=>{
  await mockSettings(page);
  await page.route('**/api/v1/communications/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/jobs'))return route.fulfill({json:{items:[{job_id:'synthetic-job',source_scope_id:scope,job_kind:'ORDINARY',state:'RUNNING',phase:null,
      counters,percentage:0,diagnostic_code:null}],next_cursor:null}});
    return route.fulfill({json:{items:[],next_cursor:null}});
  });
  await page.goto('http://127.0.0.1:4174/settings/communications');await expect(page.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(page.getByText('Owner percentage: 0%')).toHaveCount(0);
});
