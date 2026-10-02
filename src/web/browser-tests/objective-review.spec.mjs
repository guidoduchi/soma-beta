import {test,expect} from '@playwright/test';
const objective='11111111-1111-4111-8111-111111111111';
const fingerprint='a'.repeat(64);
function detail(url,review) {
  return {objective_id:objective,tracking_handle:'MW-00000001',revision:3,derived_envelope:null,aggregate_state:null,
    read_time_projection:null,membership:[],member_exact_count:0,member_continuation:null,superseded_by_objective_id:null,
    archive:{archived:true},review};
}
test('Objective renders current owner review separately from preserved stale evidence without detail fan-out',async({page})=>{
  let reads=0;
  await page.route('**/api/v1/objectives/**',route=>{
    reads++;return route.fulfill({json:detail(route.request().url(),{review_fingerprint:fingerprint,
      current:{objective_review_event_id:'synthetic-current',review_fingerprint:fingerprint,derived_outcome:'completed'},
      latest:{objective_review_event_id:'synthetic-old',review_fingerprint:'b'.repeat(64),derived_outcome:'failed',
        reviewed_at_utc:1790812800,reason_code:'SYNTHETIC_REVIEW',stale:true}})});
  });
  await page.goto('http://127.0.0.1:4174/objectives/'+objective);
  const review=page.getByRole('region',{name:'Objective review evidence'});
  await expect(review.getByText('Current owner-reviewed outcome:',{exact:false})).toContainText('completed');
  await expect(review.getByText('Latest review event:',{exact:false})).toContainText('Recorded outcome: failed');
  await expect(review.getByText('This preserved review is stale',{exact:false})).toBeVisible();
  expect(reads).toBe(1);
});
test('Objective never infers current review when owner evidence is missing or malformed',async({page})=>{
  let invalid=false;
  await page.route('**/api/v1/objectives/**',route=>route.fulfill({json:detail(route.request().url(),invalid
    ? {review_fingerprint:fingerprint,current:null,latest:{objective_review_event_id:'synthetic',review_fingerprint:fingerprint,derived_outcome:'completed',reviewed_at_utc:1000,reason_code:null}}
    : undefined)}));
  await page.goto('http://127.0.0.1:4174/objectives/'+objective);
  await expect(page.getByText('Objective review evidence is unavailable from the owner projection.')).toBeVisible();
  await expect(page.getByText('No Objective review event recorded.')).toHaveCount(0);
  invalid=true;await page.reload();
  await expect(page.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(page.getByText('Current owner-reviewed outcome:',{exact:false})).toHaveCount(0);
});
