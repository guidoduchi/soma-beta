import {test,expect} from '@playwright/test';
const id='11111111-1111-4111-8111-111111111111';
const item=(fields={})=>({proposal_id:id,revision:1,proposal_kind:'create',risk_tier:'high',origin:'manual_request',state:'pending',
  input_fingerprint:'a'.repeat(64),affected_task_exact_count:10000,affected_objective_exact_count:2,created_at_utc:1790812800,
  owner_warnings:['GROUPING_PROPOSAL_STALE'],diff:{proposal_kind:'create',risk_tier:'high',origin:'manual_request',task_change_count:10000,objective_change_count:2},...fields});
async function objectives(page){await page.route('**/api/v1/objectives?**',route=>route.fulfill({json:{items:[],exact_total:0,continuation:null,
  as_of_utc:Number(new URL(route.request().url()).searchParams.get('as_of_utc'))}}));}

test('Grouping list sends exact owner filters and opaque cursor after explicit disclosure without mutation or client reconstruction',async({page})=>{
  await objectives(page);const queries=[];
  const cursor={version:1,query_id:'GroupingProposalList',sort_registry_id:'GROUPING_PROPOSAL_CREATED_ID_ASC_V1',last_key_tuple:[1790812800,id],filter_fingerprint:'b'.repeat(64),null_order:'not_applicable'};
  await page.route('**/api/v1/grouping/proposals?**',route=>{
    expect(route.request().method()).toBe('GET');const url=new URL(route.request().url());queries.push(url);
    return route.fulfill({json:{items:[item({state:url.searchParams.get('state')??'pending'})],exact_total:300,
      continuation:queries.length===1?cursor:null}});
  });
  await page.goto('http://127.0.0.1:4174/objectives');expect(queries.length).toBe(0);
  await page.getByRole('button',{name:'Show grouping proposals'}).click();
  const list=page.getByRole('region',{name:'Grouping proposals',exact:true});
  await expect(list.getByText('300 proposals in the complete owner result; 1 on this page.')).toBeVisible();
  await expect(list.getByText('GROUPING_PROPOSAL_STALE',{exact:true})).toBeVisible();
  await expect(list.getByText('Affected Tasks: 10000; affected Objectives: 2')).toBeVisible();
  await list.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>queries.length).toBe(2);
  expect(queries[1].searchParams.get('cursor')).toBe(JSON.stringify(cursor));
  await list.getByLabel('Proposal state').selectOption('superseded');await list.getByLabel('Proposal risk').selectOption('high');
  await list.getByLabel('Proposal origin').selectOption('manual_request');expect(queries.length).toBe(2);
  await list.getByRole('button',{name:'Apply proposal filters'}).click();await expect.poll(()=>queries.length).toBe(3);
  for(const [key,value] of [['state','superseded'],['risk','high'],['origin','manual_request'],['limit','200']])expect(queries[2].searchParams.get(key)).toBe(value);
  expect(queries[2].searchParams.has('cursor')).toBe(false);
  await expect(list.getByText('State: superseded')).toBeVisible();await expect(list.locator('tbody tr')).toHaveCount(1);
});

test('Grouping list trusts affirmative owner warnings and rejects unclassified or unknown warning sets',async({page})=>{
  await objectives(page);let warnings=[];
  await page.route('**/api/v1/grouping/proposals?**',route=>route.fulfill({json:{items:[item({owner_warnings:warnings})],exact_total:1,continuation:null}}));
  await page.goto('http://127.0.0.1:4174/objectives');await page.getByRole('button',{name:'Show grouping proposals'}).click();
  const list=page.getByRole('region',{name:'Grouping proposals',exact:true});
  await expect(list.getByText('Risk: high')).toBeVisible();await expect(list.locator('.warning')).toHaveCount(0);
  for(const value of [undefined,['SYNTHETIC_UNAPPROVED_WARNING']]){
    warnings=value;await page.reload();await page.getByRole('button',{name:'Show grouping proposals'}).click();
    await expect(list.getByRole('alert')).toContainText('owner projection could not be rendered');
    await expect(list.getByText('Risk: high')).toHaveCount(0);
  }
});

test('Objective Back restores grouping disclosure and exact applied owner page, refetching changed warnings without browser-history DTOs',async({page})=>{
  await objectives(page);const queries=[];let secondReads=0;
  const cursor={version:1,query_id:'GroupingProposalList',sort_registry_id:'GROUPING_PROPOSAL_CREATED_ID_ASC_V1',
    last_key_tuple:[1790812800,id],filter_fingerprint:'b'.repeat(64),null_order:'not_applicable'};
  await page.route('**/api/v1/grouping/proposals?**',async route=>{
    expect(route.request().method()).toBe('GET');const url=new URL(route.request().url());queries.push(url.search);
    const second=url.searchParams.has('cursor');if(second)secondReads++;
    if(second&&secondReads===2)await new Promise(resolve=>setTimeout(resolve,120));
    return route.fulfill({json:{items:[item({owner_warnings:secondReads>=2?['GROUPING_EQUIVALENT_REJECTION']:['GROUPING_PROPOSAL_STALE']})],
      exact_total:300,continuation:second?null:cursor}});
  });
  await page.goto('http://127.0.0.1:4174/objectives');
  await page.getByRole('button',{name:'Show grouping proposals'}).click();
  const list=page.getByRole('region',{name:'Grouping proposals',exact:true});
  await expect(list.getByText('Risk: high')).toBeVisible();
  await list.getByLabel('Proposal state').selectOption('pending');
  await list.getByLabel('Proposal risk').selectOption('high');
  await list.getByLabel('Proposal origin').selectOption('manual_request');
  await list.getByRole('button',{name:'Apply proposal filters'}).click();
  await expect.poll(()=>queries.length).toBe(2);
  await list.getByRole('button',{name:'Next page'}).click();await expect.poll(()=>queries.length).toBe(3);
  await expect(list.getByRole('button',{name:'Next page'})).toHaveCount(0);
  await list.getByLabel('Proposal risk').focus();
  await page.getByRole('link',{name:'Inventory',exact:true}).click();
  await expect(page).toHaveURL(/\/inventory$/);await page.goBack();
  await expect(list).toBeVisible();await expect.poll(()=>queries.length).toBe(4);
  expect(queries[3]).toBe(queries[2]);
  await expect(list.getByLabel('Proposal state')).toHaveValue('pending');
  await expect(list.getByLabel('Proposal risk')).toHaveValue('high');
  await expect(list.getByLabel('Proposal origin')).toHaveValue('manual_request');
  await expect(list.getByLabel('Proposal risk')).toBeFocused();
  await expect(list.getByText('GROUPING_EQUIVALENT_REJECTION',{exact:true})).toBeVisible();
  await expect(list.getByText('GROUPING_PROPOSAL_STALE',{exact:true})).toHaveCount(0);
  const raw=await page.evaluate(()=>JSON.stringify(history.state));
  for(const forbidden of ['groupingQuery','GROUPING_','manual_request','input_fingerprint'])expect(raw).not.toContain(forbidden);
  await page.goForward();await expect(page).toHaveURL(/\/inventory$/);
  await page.goBack();await expect(list).toBeVisible();await expect.poll(()=>queries.length).toBe(5);
  expect(queries[4]).toBe(queries[2]);
  await page.getByRole('button',{name:'Hide grouping proposals'}).click();
  await page.getByRole('link',{name:'Inventory',exact:true}).click();await page.goBack();
  await expect(page.getByRole('button',{name:'Show grouping proposals'})).toBeVisible();
  await expect(list).toHaveCount(0);expect(queries.length).toBe(5);
});

test('Grouping list rejects malformed or oversized continuation before exposing navigation',async({page})=>{
  await objectives(page);let continuation={body:'unapproved copied data'};
  await page.route('**/api/v1/grouping/proposals?**',route=>route.fulfill({json:{items:[item()],exact_total:300,continuation}}));
  for(const value of [continuation,{version:1,query_id:'GroupingProposalList',sort_registry_id:'GROUPING_PROPOSAL_CREATED_ID_ASC_V1',
    last_key_tuple:[1790812800,id],filter_fingerprint:'b'.repeat(5000),null_order:'not_applicable'}]) {
    continuation=value;await page.goto('http://127.0.0.1:4174/objectives');
    await page.getByRole('button',{name:'Show grouping proposals'}).click();
    const list=page.getByRole('region',{name:'Grouping proposals',exact:true});
    await expect(list.getByRole('alert')).toContainText('owner projection could not be rendered');
    await expect(list.getByRole('button',{name:'Next page'})).toHaveCount(0);
  }
});
