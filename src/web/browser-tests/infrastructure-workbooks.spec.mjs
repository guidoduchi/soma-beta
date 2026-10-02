import {test,expect} from '@playwright/test';
const ne='33333333-3333-4333-8333-333333333333';
const runId='44444444-4444-4444-8444-444444444444';
const proposalId='55555555-5555-4555-8555-555555555555';
const hash='a'.repeat(64);
const cursor=(query,key)=>({version:1,query_id:query,sort_registry_id:query+'_ORDER_V1',last_key_tuple:key,filter_fingerprint:hash,null_order:'NOT_APPLICABLE'});
const historyCursor=cursor('InfrastructureWorkbookHistoryQuery',[100,'run',runId]);
const runCursor=cursor('InfrastructureWorkbookRunQuery',[3,'network_elements',2,proposalId]);
const proposal={proposal_id:proposalId,sheet_kind:'network_elements',row_ordinal:2,action:'unchanged',state:'pending',target_network_element_id:ne,expected_revision:2,input_fingerprint:hash,warning_codes:['SYNTHETIC_WORKBOOK_WARNING']};
const run={run_id:runId,state:'staged',revision:1,workbook_version:'SYNTHETIC-v1',mode:'round_trip',installation_relation:'foreign_installation',
  file_sha256:hash,logical_fingerprint:hash,row_counts:{network_elements:1,ip_addresses:0,warnings:1},
  proposal_counts:{pending:1,accepted:0,rejected:0,superseded:0,ambiguous:0,invalid:0},proposals:[proposal],next_cursor:runCursor};
async function setup(page,workbooks) {
  await page.route('**/api/v1/infrastructure/**',route=>{
    const url=new URL(route.request().url());
    expect(route.request().method()).toBe('GET');
    if(url.pathname.includes('/workbooks/'))return workbooks(route,url);
    if(url.pathname.endsWith('/tree'))return route.fulfill({json:{nodes:[{kind:'network_element',id:ne,label:'Synthetic workbook NE',parent_context_id:null,lifecycle:'active',warning_codes:[]}],next_cursor:null}});
    if(url.pathname.endsWith('/components'))return route.fulfill({json:{items:[],next_cursor:null}});
    if(url.pathname.endsWith('/history'))return route.fulfill({json:{events:[],next_cursor:null}});
    return route.fulfill({json:{network_element_id:ne,revision:2,lifecycle:'active',operational_name:'Synthetic workbook NE',site:{kind:'site',id:runId},customer_org_id:runId,
      placement:{rack_id:null,u_start:null,u_span:null,revision:1,explicit_unracked:true},model:null,cloud_deployment:null,primary_ip:null,ip_count:0,containment_parent:null,
      containment_child_count:0,device_reference_count:0,installed_component_count:0,warning_codes:[]}});
  });
  await page.goto('http://127.0.0.1:4174/infrastructure');
  await page.getByRole('listitem').press('Enter');
  await expect(page.getByRole('heading',{name:'Synthetic workbook NE',exact:true})).toBeVisible();
}
test('Workbook owner history/run/proposal reads retain scope, warnings, complete cursors and tab context',async({page})=>{
  let historyReads=0,runReads=0,proposalReads=0;
  await setup(page,(route,url)=>{
    if(url.pathname.endsWith('/history')) {
      historyReads++;expect(url.searchParams.get('limit')).toBe('200');
      if(url.searchParams.has('cursor')) {
        expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(historyCursor);
        return route.fulfill({json:{items:[{kind:'export',id:ne,timestamp_utc:99,state_or_mode:'discovery',filename:'SYNTHETIC-export.xlsx',sha256:hash}],next_cursor:null}});
      }
      return route.fulfill({json:{items:[{kind:'run',id:runId,timestamp_utc:100,state_or_mode:'staged',filename:'SYNTHETIC-operator.xlsx',sha256:hash}],next_cursor:historyCursor}});
    }
    if(url.pathname.includes('/runs/')) {
      runReads++;expect(url.pathname).toBe('/api/v1/infrastructure/workbooks/runs/'+runId);expect(url.searchParams.get('limit')).toBe('200');
      if(url.searchParams.has('cursor')) {
        expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(runCursor);
        return route.fulfill({json:{...run,proposals:[],next_cursor:null}});
      }
      return route.fulfill({json:run});
    }
    proposalReads++;expect(url.pathname).toBe('/api/v1/infrastructure/workbooks/proposals/'+proposalId);
    return route.fulfill({json:{proposal,impact:{creates:[],updates:[],relationship_changes:[],warning_codes:[],destructive_change:false},candidate_ids:[]}});
  });
  expect(historyReads).toBe(0);
  await page.getByRole('tab',{name:'Workbook Activity',exact:true}).click();
  const activity=page.getByRole('region',{name:'Infrastructure workbook activity'});
  await expect(activity).toContainText('Installation-wide workbook history');
  await expect(activity).toContainText('read-only and operator-managed');
  await activity.getByRole('button',{name:'Open run '+runId}).click();
  const runView=page.getByRole('region',{name:'Workbook run',exact:true});
  await expect(runView).toContainText('Foreign-installation workbook');
  await expect(runView).toContainText('Unchanged — No change');
  await runView.getByRole('button',{name:'Open proposal '+proposalId}).click();
  await expect(page.getByRole('region',{name:'Workbook proposal detail'})).toContainText('No candidate is automatically selected');
  await runView.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(runView).toContainText('No workbook proposals in this page');
  await page.getByRole('tab',{name:'Summary',exact:true}).click();
  await page.getByRole('tab',{name:'Workbook Activity',exact:true}).click();
  await expect(runView).toContainText('No workbook proposals in this page');
  expect([historyReads,runReads,proposalReads]).toEqual([1,2,1]);
  await activity.getByRole('button',{name:'Next page',exact:true}).click();
  await expect(activity).toContainText('SYNTHETIC-export.xlsx');await expect(runView).toHaveCount(0);
  await expect(activity.getByRole('button',{name:/Open run/})).toHaveCount(0);
  expect(historyReads).toBe(2);
});
test('Workbook proposal candidates obey the 200-row DOM bound without automatically choosing an identity',async({page})=>{
  const ids=Array.from({length:500},(_,index)=>`${(index+1).toString(16).padStart(8,'0')}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`);
  await setup(page,(route,url)=>route.fulfill({json:url.pathname.endsWith('/history')?
    {items:[{kind:'run',id:runId,timestamp_utc:100,state_or_mode:'staged',filename:'SYNTHETIC.xlsx',sha256:hash}],next_cursor:null}:
    url.pathname.includes('/runs/')?{...run,next_cursor:null}:
    {proposal,impact:{creates:[],updates:[],relationship_changes:[],warning_codes:[],destructive_change:false},candidate_ids:ids}}));
  await page.getByRole('tab',{name:'Workbook Activity',exact:true}).click();
  await page.getByRole('button',{name:'Open run '+runId}).click();await page.getByRole('button',{name:'Open proposal '+proposalId}).click();
  const detail=page.getByRole('region',{name:'Workbook proposal detail'});
  await expect(detail.locator('tbody tr')).toHaveCount(200);await expect(detail).toContainText('Candidate identities: 500');
  await detail.getByRole('button',{name:'Next page'}).click();await expect(detail.locator('tbody tr')).toHaveCount(200);
  await expect(detail.locator('tbody tr').first()).toHaveText(ids[200]);
  await detail.getByRole('button',{name:'Next page'}).click();await expect(detail.locator('tbody tr')).toHaveCount(100);
  await expect(detail.getByRole('button',{name:'Next page'})).toHaveCount(0);
});
for(const invalid of ['oversized','missing continuation','wrong cursor'])test(`Workbook history fails closed for ${invalid}`,async({page})=>{
  const row={kind:'run',id:runId,timestamp_utc:100,state_or_mode:'staged',filename:'SYNTHETIC.xlsx',sha256:hash};
  const response=invalid==='oversized'?{items:Array(201).fill(row),next_cursor:null}:
    invalid==='missing continuation'?{items:[row]}:{items:[row],next_cursor:{...historyCursor,query_id:'InfrastructureWorkbookRunQuery'}};
  await setup(page,route=>route.fulfill({json:response}));
  await page.getByRole('tab',{name:'Workbook Activity',exact:true}).click();
  const activity=page.getByRole('region',{name:'Infrastructure workbook activity'});
  await expect(activity.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(activity.locator('tbody tr')).toHaveCount(0);await expect(activity.getByRole('button',{name:'Next page'})).toHaveCount(0);
});

test('Infrastructure Back restores workbook history/run/proposal intent and refetches changed candidate and warning facts',async({page})=>{
  const secondProposal='66666666-6666-4666-8666-666666666666';
  const historyNext=cursor('InfrastructureWorkbookHistoryQuery',[100,'export',ne]);
  const ids=Array.from({length:500},(_,index)=>`${(index+1).toString(16).padStart(8,'0')}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`);
  const reads={history:[],run:[],proposal:[]};let changed=false;
  await page.route('**/api/v1/objectives?**',route=>route.fulfill({json:{items:[],continuation:null,exact_total:0,as_of_utc:Number(new URL(route.request().url()).searchParams.get('as_of_utc'))}}));
  await setup(page,(route,url)=>{
    if(url.pathname.endsWith('/history')) {
      reads.history.push(url.search);
      if(url.searchParams.has('cursor')) {
        expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(historyNext);
        return route.fulfill({json:{items:[{kind:'run',id:runId,timestamp_utc:99,state_or_mode:'staged',filename:'SYNTHETIC-second-history-page.xlsx',sha256:hash}],next_cursor:null}});
      }
      return route.fulfill({json:{items:[{kind:'export',id:ne,timestamp_utc:100,state_or_mode:'discovery',filename:'SYNTHETIC-first-history-page.xlsx',sha256:hash}],next_cursor:historyNext}});
    }
    if(url.pathname.includes('/runs/')) {
      reads.run.push(url.search);
      if(url.searchParams.has('cursor')) {
        expect(JSON.parse(url.searchParams.get('cursor'))).toEqual(runCursor);
        return route.fulfill({json:{...run,proposals:[{...proposal,proposal_id:secondProposal,row_ordinal:3}],next_cursor:null}});
      }
      return route.fulfill({json:run});
    }
    reads.proposal.push(url.pathname);
    return route.fulfill({json:{proposal:{...proposal,proposal_id:secondProposal,row_ordinal:3},
      impact:{creates:[],updates:[],relationship_changes:[],warning_codes:changed?['SYNTHETIC_CURRENT_IMPACT_WARNING']:[],destructive_change:false},
      candidate_ids:changed?ids.slice(0,120):ids}});
  });
  await page.getByRole('tab',{name:'Workbook Activity',exact:true}).click();
  const activity=page.getByRole('region',{name:'Infrastructure workbook activity'});
  await activity.getByRole('button',{name:'Next page',exact:true}).click();await activity.getByRole('button',{name:'Open run '+runId}).click();
  const runView=page.getByRole('region',{name:'Workbook run',exact:true});await runView.getByRole('button',{name:'Next page',exact:true}).click();
  await runView.getByRole('button',{name:'Open proposal '+secondProposal}).click();
  const detail=page.getByRole('region',{name:'Workbook proposal detail'});
  await detail.getByRole('button',{name:'Next page'}).click();await detail.getByRole('button',{name:'Next page'}).click();
  await expect(detail.locator('tbody tr')).toHaveCount(100);
  await page.getByRole('link',{name:'Objectives',exact:true}).click();changed=true;await page.goBack();
  await expect(page.getByRole('tab',{name:'Workbook Activity',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(detail.locator('tbody tr')).toHaveCount(120);await expect(detail).toContainText('SYNTHETIC_CURRENT_IMPACT_WARNING');
  await expect(detail).toContainText('The previous candidate page is unavailable; the first current candidate page is shown.');
  expect(reads.history.at(-1)).toBe(reads.history[1]);expect(reads.run.at(-1)).toBe(reads.run[1]);expect(reads.proposal.at(-1)).toBe(reads.proposal[0]);
  expect(JSON.stringify(await page.evaluate(()=>history.state))).not.toContain('SYNTHETIC');
});
