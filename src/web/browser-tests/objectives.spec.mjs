import {test,expect} from '@playwright/test';
const objectiveId='11111111-1111-4111-8111-111111111111';
const taskId='22222222-2222-4222-8222-222222222222';
const interval={start_utc:1000,end_utc:2000};
const aggregate={execution_state:'planned',aggregate_outcome:null,actual_start_utc:null,actual_end_utc:null,
  attention_reason:null,included_task_count:201,excluded_task_count:0};
function readTime(asOf) {return {as_of_utc:asOf,effective_review_state:'awaiting_review',due_unreviewed:true,reason_codes:['due_unreviewed']};}
test('compiled Objective list opens only explicitly and preserves owner envelope, attention and bounded membership', async ({page}) => {
  const queries=[];
  await page.route('**/api/v1/objectives**', route => {
    const url=new URL(route.request().url()); queries.push(url); const asOf=Number(url.searchParams.get('as_of_utc'));
    expect(Number.isSafeInteger(asOf)).toBe(true);
    if (url.pathname === '/api/v1/objectives') {
      expect(url.searchParams.get('limit')).toBe('200');
      return route.fulfill({json:{items:[{objective_id:objectiveId,tracking_handle:'MW-00000001',revision:1,derived_envelope:interval,
        aggregate_state:aggregate,read_time_projection:readTime(asOf),archived:false}],continuation:{synthetic:'next'},exact_total:2,as_of_utc:asOf}});
    }
    expect(url.searchParams.get('member_limit')).toBe('200');
    return route.fulfill({json:{objective_id:objectiveId,tracking_handle:'MW-00000001',revision:1,derived_envelope:interval,
      aggregate_state:aggregate,read_time_projection:readTime(asOf),member_exact_count:201,
      membership:[{task_id:taskId,display_name:'Synthetic Task Alpha',task_kind:'wfm',accepted_plan:interval,
        accepted_plan_revision_id:'synthetic-pinned',current_plan_revision_id:'synthetic-current',current_plan_revision:2,plan_membership_mismatch:true}],
      member_continuation:{synthetic:'members-next'},superseded_by_objective_id:null,archive:{archived:false}}});
  });
  await page.goto('http://127.0.0.1:4174/objectives');
  const row=page.getByRole('listitem'); await expect(row).toContainText('MW-00000001');
  await row.click(); await expect(page).toHaveURL(/\/objectives$/); await expect(row).toHaveAttribute('aria-current','true');
  await row.press('Enter'); await expect(page).toHaveURL(new RegExp('/objectives/'+objectiveId+'$'));
  await expect(page.getByRole('heading',{name:'Objective envelope',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Actual execution',exact:true})).toBeVisible();
  await expect(page.getByText('Actual start:')).toContainText('Unknown');
  await expect(page.getByText('Due and unreviewed.')).toBeVisible();
  await expect(page.getByText('201 accepted members; 1 on this page.')).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(1); await expect(page.getByText('PLAN_MEMBERSHIP_MISMATCH:',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Next page'}).click();
  await expect.poll(()=>queries.at(-1).searchParams.get('member_cursor')).toBe(JSON.stringify({synthetic:'members-next'}));
  expect(queries.length).toBe(3); // No per-member detail query fan-out.
});
test('Objective read-time identity mismatch fails closed rather than displaying fabricated attention', async ({page}) => {
  await page.route('**/api/v1/objectives?**',route=>route.fulfill({json:{items:[],continuation:null,exact_total:0,as_of_utc:0}}));
  await page.goto('http://127.0.0.1:4174/objectives');
  await expect(page.getByRole('alert')).toContainText('owner projection could not be rendered');
});

test('Objective refresh restores the nearest surviving selection without opening or moving focus from Refresh',async({page})=>{
  let reads=0;const instants=[];await page.clock.install({time:new Date('2026-10-01T00:00:00Z')});
  await page.route('**/api/v1/objectives?**',route=>{
    const asOf=Number(new URL(route.request().url()).searchParams.get('as_of_utc'));reads++;instants.push(asOf);
    const ids=reads===1?['synthetic-A','synthetic-B','synthetic-C','synthetic-D']:['synthetic-A','synthetic-B','synthetic-D'];
    return route.fulfill({json:{items:ids.map(id=>({objective_id:id,tracking_handle:id,revision:1,derived_envelope:interval,
      aggregate_state:aggregate,read_time_projection:readTime(asOf),archived:false})),continuation:null,exact_total:ids.length,as_of_utc:asOf}});
  });
  await page.goto('http://127.0.0.1:4174/objectives');const selected=page.getByRole('listitem').filter({hasText:'synthetic-C'});
  await selected.click();await expect(selected).toHaveAttribute('aria-current','true');
  const refresh=page.getByRole('button',{name:'Refresh Objective attention'});await refresh.click();
  await expect(page.getByRole('listitem').filter({hasText:'synthetic-B'})).toHaveAttribute('aria-current','true');
  await expect(page.getByRole('status')).toContainText('previous row is unavailable');await expect(refresh).toBeFocused();
  await expect(page).toHaveURL(/\/objectives$/);expect(reads).toBe(2);expect(instants[0]).toBe(instants[1]);
});

test('Objective Back restores the exact page query and nearest surviving row; Forward keeps explicit detail navigation',async({page})=>{
  const listReads=[];let secondPageReads=0;
  await page.route('**/api/v1/objectives**',async route=>{
    const url=new URL(route.request().url());const asOf=Number(url.searchParams.get('as_of_utc'));
    if(url.pathname!=='/api/v1/objectives')return route.fulfill({json:{objective_id:'synthetic-C',tracking_handle:'synthetic-C',revision:1,derived_envelope:interval,
      aggregate_state:aggregate,read_time_projection:readTime(asOf),member_exact_count:0,membership:[],member_continuation:null,superseded_by_objective_id:null,archive:{archived:false}}});
    listReads.push(url.search);const second=url.searchParams.has('cursor');if(second)secondPageReads++;
    const ids=second?(secondPageReads===1?['synthetic-A','synthetic-B','synthetic-C','synthetic-D']:['synthetic-A','synthetic-B','synthetic-D']):['synthetic-first'];
    if(second&&secondPageReads===2)await new Promise(resolve=>setTimeout(resolve,120));
    return route.fulfill({json:{items:ids.map(id=>({objective_id:id,tracking_handle:id,revision:1,derived_envelope:interval,aggregate_state:aggregate,
      read_time_projection:readTime(asOf),archived:false})),continuation:second?null:{synthetic:'second-page'},exact_total:5,as_of_utc:asOf}});
  });
  await page.goto('http://127.0.0.1:4174/objectives');await page.getByRole('button',{name:'Next Objective page'}).click();
  const chosen=page.getByRole('listitem').filter({hasText:'synthetic-C'});await chosen.click();await chosen.getByRole('button',{name:'Open record'}).click();
  await expect(page).toHaveURL(/\/objectives\/synthetic-C$/);await page.goBack();
  await expect(page).toHaveURL(/\/objectives$/);const nearest=page.getByRole('listitem').filter({hasText:'synthetic-B'});
  await expect(nearest).toHaveAttribute('aria-current','true');await expect(nearest).toBeFocused();
  expect(listReads.length).toBe(3);expect(listReads[1]).toBe(listReads[2]);
  await expect(page.getByText('previous control is unavailable',{exact:false})).toBeVisible();
  const historyState=await page.evaluate(()=>JSON.stringify(history.state));expect(historyState).not.toContain('collectionQuery');expect(historyState).not.toContain('synthetic');
  await page.goForward();await expect(page).toHaveURL(/\/objectives\/synthetic-C$/);
});
