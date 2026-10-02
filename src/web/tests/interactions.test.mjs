import {test} from 'node:test';
import assert from 'node:assert/strict';
import {selectionOpen, restoreSelection} from '../.test-build/interactions/selection-open.js';
import {emptySelection,UiStore} from '../.test-build/state/ui-store.js';
import {QueryController, filterFingerprint} from '../.test-build/data/query-controller.js';
import {createHash} from 'node:crypto';
import {DeliberateHold} from '../.test-build/interactions/deliberate-hold.js';
import {SafeUndo} from '../.test-build/interactions/safe-undo.js';
import {classifyContainer} from '../.test-build/layout/responsive.js';
import {resolveRoute, defaultOpen, NavigationHistory, RouteNavigation,objectiveCollectionQuery,groupingCollectionQuery,inventoryCollectionQueries,infrastructureIntent,infrastructureQuery} from '../.test-build/app/router.js';
import {boundedOptions} from '../.test-build/interactions/autocomplete.js';
import {confirmationTier} from '../.test-build/components/ActionButton.js';
import {AppearanceController} from '../.test-build/state/appearance.js';
import {WorkingCopyClient} from '../.test-build/working-copy/client.js';
import {settingsQuery,settingsIntent,nextSettingsQuery} from '../.test-build/app/settings-intent.js';

const row = {id: 'row-A', eligible: true, route: {record_type: 'RFC', record_id: 'row-A', revision_token: '1'}};

test('Settings history contains only closed owner queries and frozen opened identity intent',()=>{
  const id='11111111-1111-4111-8111-111111111111';
  const base='/api/v1/product-lines?limit=200';
  const cursor={version:1,query_id:'ListProductLines',sort_registry_id:'PRODUCT_LINE_PRESENTATION_ASC_V1',last_key_tuple:['synthetic',id],filter_fingerprint:'a'.repeat(64),null_order:'none'};
  const path=nextSettingsQuery(base,'products',cursor);assert.deepEqual(settingsQuery(path,'products').cursor,cursor);
  const settings={queries:{products:path},opened:{customers:null,contacts:null,dispatch:null,source:null},accountHistory:false};
  assert.ok(settingsIntent(settings,'/settings'));assert.equal(settingsIntent(settings,'/settings/communications'),null);
  for(const bad of [{...cursor,last_key_tuple:['synthetic']},{...cursor,query_id:'ListContracts'},{...cursor,draft:'not permitted'}])assert.throws(()=>nextSettingsQuery(base,'products',bad));
  assert.equal(settingsQuery(base+'&limit=200','products'),null);assert.equal(settingsQuery(base+'&draft=synthetic','products'),null);
  assert.equal(settingsQuery(base+'&cursor='+encodeURIComponent(JSON.stringify({...cursor,last_key_tuple:['x'.repeat(4096),id]})),'products'),null);
  const history=new NavigationHistory();const token=history.remember({route:'/settings',filterFingerprint:'a'.repeat(64),activeId:null,selectedId:null,memberIds:[],scrollAnchor:null,focusToken:null,settings});
  settings.queries.products=base;settings.opened.customers=id;
  assert.equal(history.restore(token).settings.queries.products,path);assert.equal(history.restore(token).settings.opened.customers,null);
  assert.throws(()=>history.remember({...history.restore(token),route:'/tickets'}));
  assert.equal(settingsIntent({...settings,queries:{channels:`/api/v1/reference/contacts/${id}/channels?limit=200&include_archived=true`}},'/settings'),null);
});
test('LLD10-T001-T004 selection, membership and explicit opening are independent', () => {
  const selected = selectionOpen(emptySelection, {kind: 'click', row, nestedControl: false});
  assert.equal(selected.selected_id, row.id); assert.equal(selected.opened_ref, null);
  assert.equal(selectionOpen(selected, {kind: 'open', row, nestedControl: true}), selected);
  const members = selectionOpen(selected, {kind: 'space', row, multi: true});
  assert.deepEqual(members.member_ids, [row.id]); assert.equal(members.opened_ref, null);
  assert.deepEqual(selectionOpen(members, {kind: 'arrow', row: {...row, id: 'B'}, selectionFollowsFocus: false}).member_ids, [row.id]);
  assert.deepEqual(selectionOpen(members, {kind: 'open', row, nestedControl: false}).opened_ref, row.route);
  assert.equal(selectionOpen(members, {kind: 'open', row: {...row, eligible: false}, nestedControl: false}), members);
  assert.match(restoreSelection(members, []).explanation, /unavailable/);
});
test('LLD10-T009 F009 F010 only complete newest query identity accepts response or error', () => {
  const queries = new QueryController(); const a = queries.start('surface', 'one', 'a'.repeat(64));
  const b = queries.start('surface', 'two', 'a'.repeat(64));
  assert.equal(a.signal.aborted, true); assert.equal(queries.accept_response(a.identity), false);
  for (const field of ['query_id', 'sequence', 'normalized_input', 'filter_fingerprint']) assert.equal(queries.accept_response({...b.identity, [field]: field === 'sequence' ? 90 : 'changed'}), false);
  assert.equal(queries.accept_response(b.identity), true); queries.cancel('surface'); assert.equal(queries.accept_response(b.identity), false);
});
test('collection order keeps only bounded identity intent and nearest-row restoration respects previous order',()=>{
  const store=new UiStore({selection:emptySelection,tab:'List',pane:'work',filters:{},scrollAnchors:{},dirty:false,errors:{},focusToken:null});
  const ids=['A','B','C','D'];store.rememberCollectionOrder(ids);ids[0]='changed';
  assert.deepEqual(store.getCollectionOrder(),['A','B','C','D']);
  const rows=['A','B','D'].map(id=>({...row,id}));
  const restored=restoreSelection({...emptySelection,active_id:'C',selected_id:'C'},rows,store.getCollectionOrder());
  assert.equal(restored.selection.active_id,'B');assert.equal(restored.selection.selected_id,'B');
  assert.equal(restored.selection.opened_ref,null);
  assert.throws(()=>store.rememberCollectionOrder(Array.from({length:201},(_,i)=>String(i))));
  assert.throws(()=>store.rememberCollectionOrder(['duplicate','duplicate']));
});
test('filter fingerprint uses canonical code-point ordering including numeric keys', async () => {
  const expected = createHash('sha256').update('{"1":"a","10":"b","2":"c","A":"d","a":"e"}').digest('hex');
  assert.equal(await filterFingerprint({'2':'c', '10':'b', '1':'a', a:'e', A:'d'}), expected);
});
test('LLD10-T010 autocomplete cannot silently truncate pages or append beyond 50', () => {
  const page = {items: Array.from({length: 25}, (_, i) => ({id: String(i), label: String(i), eligible: true, reason: null})), nextCursor: 'next'};
  assert.equal(boundedOptions([], page).length, 25);
  const second = {...page, items: page.items.map(value => ({...value, id: 'B' + value.id}))};
  assert.equal(boundedOptions(page.items, second).length, 50);
  assert.throws(() => boundedOptions([...page.items, ...second.items], {items: [{...page.items[0], id: 'extra'}], nextCursor: null}));
  assert.throws(() => boundedOptions(page.items, page));
});
const binding = {actionKind: 'tickets.rfc.terminal_cascade.execute', targetType: 'rfc', targetId: 'rfc-A', revision: 1, previewFingerprint: 'a'.repeat(64), route: '/tickets/rfc/rfc-A'};
function holdSetup() {
  let time = 0; let calls = 0;
  const hold = new DeliberateHold({issue: async () => ({challengeId: 'challenge', clientNonce: 'nonce', expiresMonotonicMs: 10000}),
    complete: async () => 'proof', submit: async () => {calls++; return 'accepted';}}, () => time);
  return {hold, time: value => {time = value;}, calls: () => calls};
}
test('LLD10-T012-T014 continuous exact 3000ms and one-shot command', async () => {
  const value = holdSetup(); await value.hold.start(binding, true); value.time(2999);
  assert.equal(await value.hold.finish(binding), null); assert.equal(value.calls(), 0);
  value.time(3000); const both = await Promise.all([value.hold.finish(binding), value.hold.finish(binding)]);
  assert.equal(both.filter(result => result === 'accepted').length, 1); assert.equal(value.calls(), 1);
});
test('LLD10-F012-F014 cancellation, target drift and late challenge never submit', async () => {
  for (const drift of [{...binding, revision: 2}, {...binding, route: '/inventory'}, {...binding, previewFingerprint: 'b'.repeat(64)}]) {
    const value = holdSetup(); await value.hold.start(binding, true); value.time(3000); assert.equal(await value.hold.finish(drift), null); assert.equal(value.calls(), 0);
  }
  const cancelled = holdSetup(); await cancelled.hold.start(binding, true); cancelled.hold.cancel(); cancelled.time(3000); await cancelled.hold.finish(binding); assert.equal(cancelled.calls(), 0);
  let issued; let calls = 0;
  const hold = new DeliberateHold({issue: () => new Promise(resolve => {issued = resolve;}), complete: async () => {throw new Error('expired');}, submit: async () => {calls++;}}, () => 0);
  const pending = hold.start(binding, true); hold.cancel(); issued({challengeId: 'late', clientNonce: 'nonce', expiresMonotonicMs: 10000}); await pending;
  assert.equal(hold.phase, 'cancelled'); assert.equal(calls, 0);
});
test('LLD10-T038 T041 T042 F021 F022 Undo is owner scoped, capped and refreshed at execution', async () => {
  let available = true; let submits = 0;
  const owner = {commandContract: 'OwnerCorrectionV1', preview: async () => ({state: available ? 'AVAILABLE' : 'STALE', fingerprint: 'a'.repeat(64), reason: 'Owner revision'}),
    build: async () => ({exactOwnerDto: true}), submit: async () => {if (!available) throw new Error('STALE_REVISION'); submits++;}};
  const undo = new SafeUndo(new Map([['LLD-03:correct', owner]]));
  for (let i = 0; i < 21; i++) undo.remember({id: String(i), owner: 'LLD-03', inverseKind: 'correct', actionResultRef: 'result-' + i, target: row.route, postRevision: '1'});
  assert.equal(undo.list().length, 20); assert.equal(undo.list()[0].id, '1');
  available = false; assert.equal(await undo.execute('20'), false); assert.equal(submits, 0);
  available = true; assert.equal(await undo.execute('19'), true); assert.equal(await undo.execute('19'), false); assert.equal(submits, 1);
  assert.equal(undo.remember({id: 'unknown', owner: 'LLD-03', inverseKind: 'invented', actionResultRef: 'x', target: row.route, postRevision: '1'}), false);
});
test('LLD10-F021 owner state changing after inverse preview rejects without local rollback', async () => {
  let revision=1, acceptedMutations=0, submissions=0;
  const owner={commandContract:'OwnerCorrectionV1',
    preview:async()=>({state:'AVAILABLE',fingerprint:'a'.repeat(64),reason:null}),
    build:async(opportunity,fingerprint)=>{revision=2;return {baseRevision:Number(opportunity.postRevision),fingerprint};},
    submit:async(contract,request)=>{
      submissions++;assert.equal(contract,'OwnerCorrectionV1');assert.equal(request.fingerprint,'a'.repeat(64));
      if(request.baseRevision!==revision)throw new Error('STALE_REVISION');
      acceptedMutations++;
    }};
  const undo=new SafeUndo(new Map([['LLD-03:correct',owner]]));
  undo.remember({id:'synthetic',owner:'LLD-03',inverseKind:'correct',actionResultRef:'accepted-result',target:row.route,postRevision:'1'});
  assert.equal(await undo.execute('synthetic'),false);
  assert.equal(submissions,1);assert.equal(acceptedMutations,0);assert.equal(revision,2);
  assert.equal(undo.list().length,1);
});

test('LLD10-T016 T018 container boundaries and route history remain bounded', () => {
  assert.deepEqual([719,720,1199,1200].map(classifyContainer), ['narrow','standard','standard','wide']);
  assert.equal(resolveRoute('/api/v1/tickets'), null); assert.equal(resolveRoute('/tickets/sr/a%2fb'), null);
  assert.equal(defaultOpen('RFC', 'synthetic-id').path, '/tickets/rfc/synthetic-id');
  const history = new NavigationHistory(); let first;
  for (let i=0; i<51; i++) {const token = history.remember({route: '/tickets', filterFingerprint: 'a', activeId: null, selectedId: null, memberIds: [], scrollAnchor: null, focusToken: null}); if (i === 0) first = token;}
  assert.equal(history.restore(first), null);
});
test('Back/Forward restores bounded intent and dirty Back waits for explicit review', () => {
  const stack = []; const movements = []; let dirty = false, currentPath = '/tickets', asked = null, received = null;
  let context = {route:'/tickets',filterFingerprint:'a'.repeat(64),activeId:'row',selectedId:'row',memberIds:[],scrollAnchor:'row',focusToken:'row'};
  const nav = new RouteNavigation(currentPath, {replace: state => {stack[0] = state;}, push: state => stack.push(state), go: delta => movements.push(delta)},
    () => dirty, () => context, (path, restored) => {currentPath = path; received = restored;}, path => {asked = path;});
  nav.navigate('/tickets/sr/target'); context = null;
  dirty = true; nav.pop('/tickets', stack[0]); assert.equal(currentPath, '/tickets/sr/target'); assert.deepEqual(movements, [1]);
  nav.pop('/tickets/sr/target', stack[1]); assert.equal(asked, '/tickets'); nav.cancel(); assert.equal(asked, null);
  nav.pop('/tickets', stack[0]); nav.pop('/tickets/sr/target', stack[1]); dirty = false; nav.confirm();
  assert.equal(movements.at(-1), -1); nav.pop('/tickets', stack[0]);
  assert.equal(currentPath, '/tickets'); assert.equal(received.selectedId, 'row');
  nav.navigate('/inventory'); context = null; nav.pop('/tickets', stack[0]);
  assert.equal(currentPath, '/tickets'); assert.equal(received.activeId, 'row');
});
test('collection return context preserves bounded immutable identity order and closed Objective query intent',()=>{
  const query='/api/v1/objectives?limit=200&as_of_utc=123&cursor='+encodeURIComponent(JSON.stringify({synthetic:'next'}));
  assert.deepEqual(objectiveCollectionQuery(query),{asOf:123,cursor:{synthetic:'next'}});
  for(const invalid of ['/api/v1/tasks?limit=200&as_of_utc=123',query+'&draft=private',query+'&as_of_utc=124',
    '/api/v1/objectives?limit=200&as_of_utc=-1','/api/v1/objectives?limit=200&as_of_utc=0&cursor=invalid'])assert.equal(objectiveCollectionQuery(invalid),null);
  const history=new NavigationHistory();const order=['A','B'];
  const token=history.remember({route:'/objectives',filterFingerprint:'a'.repeat(64),activeId:'B',selectedId:'B',memberIds:[],scrollAnchor:null,focusToken:'row:B',
    collectionQuery:query,collectionOrder:order});order[1]='changed';
  assert.deepEqual(history.restore(token).collectionOrder,['A','B']);
  assert.throws(()=>history.remember({...history.restore(token),collectionOrder:['A','A']}));
  assert.throws(()=>history.remember({...history.restore(token),collectionQuery:query+'&draft=private'}));
});
test('LLD10-T054 F025 unknown confirmation stays disabled and owner-reconciled hard-delete preserves hold', () => {
  assert.equal(confirmationTier('unknown'), null); assert.equal(confirmationTier('tickets.rfc.hard_delete'), 'impact_preview_plus_hold');
  assert.equal(confirmationTier('tickets.rfc.terminal_cascade.execute'), 'impact_preview_plus_hold');
});
test('LLD10-F015 failed appearance save restores accepted presentation', async () => {
  let shown; const initial = {mode: 'light', skin: 'soma_core'};
  const controller = new AppearanceController(initial, value => {shown = value;});
  assert.equal(await controller.previewAndSave({mode: 'dark', skin: 'terminal_green'}, async () => {throw new Error('offline');}), false);
  assert.deepEqual(shown, initial);
});
test('an older appearance response cannot replace the newer accepted preview', async () => {
  let shown, resolveOld;
  const initial = {mode: 'light', skin: 'soma_core'};
  const newer = {mode: 'dark', skin: 'terminal_violet'};
  const controller = new AppearanceController(initial, value => {shown = value;});
  const old = controller.previewAndSave({mode: 'dark', skin: 'terminal_green'}, () => new Promise(resolve => {resolveOld = resolve;}));
  await controller.previewAndSave(newer, async value => value);
  resolveOld(initial); await old;
  await controller.previewAndSave(initial, async () => {throw new Error('failed');});
  assert.deepEqual(shown, newer);
});
test('a cancelled checkpoint cannot clear a newer pending checkpoint', async () => {
  let time = 0; const pending = [];
  const client = new WorkingCopyClient(() => new Promise(resolve => pending.push(resolve)), () => {}, () => time);
  client.edit({note: 'old'}); time = 5000; const old = client.checkpoint();
  client.acceptedSave(); client.edit({note: 'new'}); time = 10000; const newer = client.checkpoint();
  pending[0]({workingCopyId:'11111111-1111-4111-8111-111111111111',generation: 1, contentHash: 'a'.repeat(64)}); await old;
  assert.equal(client.status, 'pending');
  pending[1]({workingCopyId:'11111111-1111-4111-8111-111111111111',generation: 1, contentHash: 'b'.repeat(64)}); await newer;
  assert.equal(client.status, 'checkpointed'); assert.deepEqual(client.memory(), {note: 'new'});
  client.dispose();
});
test('LLD10-F020 recovery cadence and failed checkpoint preserve memory without false success', async () => {
  let time = 0; let requests = 0;
  const client = new WorkingCopyClient(async () => {requests++; throw new Error('offline');}, () => {}, () => time);
  client.edit({note: 'synthetic intent'}); assert.equal(client.status, 'memory_only'); assert.equal(client.hasUnsavedIntent(), true);
  await client.checkpoint(); assert.equal(requests, 0);
  time = 5000; await client.checkpoint(); assert.equal(requests, 1); assert.equal(client.status, 'error'); assert.deepEqual(client.memory(), {note: 'synthetic intent'});
  client.dispose();
});

test('LLD10-T019-T021 restored copies remain unsaved; missing and stale authority cannot checkpoint', async () => {
  for (const freshness of ['CURRENT','STALE','TARGET_MISSING','INDETERMINATE']) {
    let calls=0;
    const client=new WorkingCopyClient(async()=>{calls++; throw new Error('must not checkpoint');},()=>{},()=>100000);
    client.restore({note:'synthetic restored intent'},{workingCopyId:'11111111-1111-4111-8111-111111111111',generation:2,contentHash:'a'.repeat(64)},freshness);
    assert.equal(client.hasUnsavedIntent(),true); assert.deepEqual(client.memory(),{note:'synthetic restored intent'});
    assert.equal(client.status,freshness === 'CURRENT' ? 'checkpointed' : 'conflict');
    if (freshness !== 'CURRENT') {await client.checkpoint(); assert.equal(calls,0);}
    client.dispose();
  }
});

test('successful recovery checkpoint enforces 30 seconds and rejects changed identity or skipped generations', async () => {
  let time=0, calls=0;
  const copyId='11111111-1111-4111-8111-111111111111';
  let result={workingCopyId:copyId,generation:1,contentHash:'a'.repeat(64)};
  const client=new WorkingCopyClient(async()=>{calls++; return result;},()=>{},()=>time);
  client.edit({note:'first'}); time=5000; await client.checkpoint(); assert.equal(client.status,'checkpointed');
  time=6000; client.edit({note:'second'}); time=34999; await client.checkpoint(); assert.equal(calls,1);
  time=35000; result={...result,generation:3}; await client.checkpoint(); assert.equal(client.status,'error');
  assert.deepEqual(client.memory(),{note:'second'});
  result={...result,generation:2,workingCopyId:'22222222-2222-4222-8222-222222222222'}; await client.checkpoint(); assert.equal(client.status,'error');
  result={...result,workingCopyId:copyId}; await client.checkpoint(); assert.equal(client.status,'checkpointed');
  client.dispose();
});

test('LLD10-T020-T021 editing a conflicted restore preserves intent without resubmitting stale authority', async () => {
  for (const freshness of ['STALE','TARGET_MISSING','INDETERMINATE']) {
    let time=0, calls=0;
    const client=new WorkingCopyClient(async()=>{calls++; throw new Error('unexpected checkpoint');},()=>{},()=>time);
    try {
      client.restore({note:'restored'}, {workingCopyId:'11111111-1111-4111-8111-111111111111',generation:2,contentHash:'a'.repeat(64)},freshness);
      client.edit({note:'operator correction'}); time=100000; await client.checkpoint();
      assert.equal(calls,0); assert.equal(client.status,'conflict');
      assert.deepEqual(client.memory(),{note:'operator correction'}); assert.equal(client.hasUnsavedIntent(),true);
      assert.throws(()=>client.restore({note:'implicit rebase'},{workingCopyId:'11111111-1111-4111-8111-111111111111',generation:3,contentHash:'b'.repeat(64)},'CURRENT'));
    } finally {client.dispose();}
  }
});

test('checkpoint generation conflict remains blocked through subsequent edits', async () => {
  let time=0, calls=0, reject;
  const client=new WorkingCopyClient(()=>{calls++; return new Promise((_, failure)=>{reject=failure;});},()=>{},()=>time);
  try {
    client.edit({note:'first'}); time=5000; const pending=client.checkpoint();
    client.edit({note:'edited during pending checkpoint'});
    reject(new Error('UI_WORKING_COPY_CONFLICT')); await pending;
    client.edit({note:'edited after conflict'}); time=100000; await client.checkpoint();
    assert.equal(calls,1); assert.equal(client.status,'conflict'); assert.deepEqual(client.memory(),{note:'edited after conflict'});
  } finally {client.dispose();}
});

test('disposed recovery clients ignore edits and late failures without notifying an unmounted flow', async () => {
  let time=0, notifications=0, reject;
  const client=new WorkingCopyClient(()=>new Promise((_, failure)=>{reject=failure;}),()=>{notifications++;},()=>time);
  client.edit({note:'retained'}); time=5000; const pending=client.checkpoint();
  client.dispose(); const before=notifications;
  client.edit({note:'late edit'}); client.acceptedSave(); reject(new Error('offline')); await pending;
  assert.equal(notifications,before); assert.deepEqual(client.memory(),{note:'retained'});
  assert.throws(()=>client.restore({note:'late restore'},{workingCopyId:'11111111-1111-4111-8111-111111111111',generation:1,contentHash:'a'.repeat(64)},'CURRENT'));
});

test('recovery cancellation from the pending notification submits no transport request', async () => {
  let time=0, calls=0;
  const client=new WorkingCopyClient(async()=>{calls++; throw new Error('unexpected request');},()=>{if(client.status === 'pending')client.acceptedSave();},()=>time);
  try {
    client.edit({note:'accepted elsewhere'}); time=5000; await client.checkpoint();
    assert.equal(calls,0); assert.equal(client.hasUnsavedIntent(),false); assert.equal(client.status,'memory_only');
  } finally {client.dispose();}
});

test('LLD10-T015 F013 late or rejected proofs and owner rejection never report accepted action', async () => {
  for (const point of ['proof','owner','cancelled-proof']) {
    let time=0, calls=0, resolveProof;
    const hold=new DeliberateHold({issue:async()=>({challengeId:'synthetic',clientNonce:'synthetic',expiresMonotonicMs:10000}),
      complete:()=>point === 'cancelled-proof' ? new Promise(resolve=>{resolveProof=resolve;}) : point === 'proof' ? Promise.reject(new Error('PROOF_EXPIRED')) : Promise.resolve('synthetic-proof'),
      submit:async()=>{calls++; throw new Error('OWNER_STALE');}},()=>time);
    await hold.start(binding,true); time=3000; const pending=hold.finish(binding);
    if (point === 'cancelled-proof') {hold.cancel(); resolveProof('late-proof');}
    assert.equal(await pending,null); assert.equal(calls,point === 'owner' ? 1 : 0);
    assert.notEqual(hold.phase,'submitted');
  }
});

test('grouping return intent is closed, bounded and kept out of unrelated route contexts',()=>{
  const cursor={version:1,query_id:'GroupingProposalList',sort_registry_id:'GROUPING_PROPOSAL_CREATED_ID_ASC_V1',
    last_key_tuple:[123,'11111111-1111-4111-8111-111111111111'],filter_fingerprint:'b'.repeat(64),null_order:'not_applicable'};
  const query='/api/v1/grouping/proposals?limit=200&state=superseded&risk=high&origin=manual_request&cursor='+encodeURIComponent(JSON.stringify(cursor));
  assert.deepEqual(groupingCollectionQuery(query),{filters:{state:'superseded',risk:'high',origin:'manual_request'},cursor});
  for(const value of [{...cursor,body:'private'},{...cursor,version:2},{...cursor,query_id:'TaskAttentionList'},
    {...cursor,sort_registry_id:'unknown'},{...cursor,null_order:'unknown'},{...cursor,filter_fingerprint:'invalid'},
    {...cursor,last_key_tuple:[123]},{...cursor,last_key_tuple:[-1,cursor.last_key_tuple[1]]},
    {...cursor,last_key_tuple:[123,'invalid']},[],{},'body-bearing-value']) {
    assert.equal(groupingCollectionQuery('/api/v1/grouping/proposals?limit=200&cursor='+encodeURIComponent(JSON.stringify(value))),null);
  }
  for(const invalid of [query+'&draft=private',query+'&state=pending',query+'#fragment',query.replace('superseded','unknown'),
    query.replace('high','unknown'),query.replace('manual_request','unknown'),query.replace('limit=200','limit=500'),
    '/api/v1/grouping/proposals?limit=200&cursor=invalid','/api/v1/grouping/proposals?limit=200&state=',
    '/api/v1/grouping/proposals?limit=200&cursor='+encodeURIComponent(JSON.stringify('x'.repeat(4096)))])assert.equal(groupingCollectionQuery(invalid),null);
  const history=new NavigationHistory();
  const state={route:'/objectives',filterFingerprint:'a'.repeat(64),activeId:null,selectedId:null,memberIds:[],scrollAnchor:null,focusToken:'grouping:apply',groupingQuery:query};
  const token=history.remember(state);state.groupingQuery=null;
  assert.equal(history.restore(token).groupingQuery,query);
  assert.throws(()=>history.remember({...state,route:'/inventory',groupingQuery:query}));
  assert.throws(()=>history.remember({...state,groupingQuery:query+'&body=private'}));
  assert.equal(history.restore(history.remember(state)).groupingQuery,null);
});

test('Inventory return context retains only two bounded closed read intents with complete owner cursors',()=>{
  const stockCursor={version:1,query_id:'StockEligibilityQuery',sort_registry_id:'INVENTORY_STOCK_COMPAT_LSU_ID_ASC_V1',
    last_key_tuple:[3,'LSU-SYNTHETIC','55555555-5555-4555-8555-555555555555'],filter_fingerprint:'a'.repeat(64),null_order:'empty_before_text'};
  const attentionCursor={version:1,query_id:'InventoryAttentionQuery',sort_registry_id:'INVENTORY_ATTENTION_CANONICAL_V1',
    last_key_tuple:[2,'warehouse_rejected_resend_required','rma','55555555-5555-4555-8555-555555555555'],filter_fingerprint:'b'.repeat(64),null_order:'not applicable'};
  const queries={stock:'/api/v1/inventory/stock?limit=200&cursor='+encodeURIComponent(JSON.stringify(stockCursor)),
    attention:'/api/v1/inventory/attention?limit=200&as_of_utc=123&cursor='+encodeURIComponent(JSON.stringify(attentionCursor))};
  assert.deepEqual(inventoryCollectionQueries(queries),{stockCursor,attentionCursor,asOf:123});
  for(const invalid of [{...queries,body:'private'},{...queries,stock:queries.stock+'&limit=200'},
    {...queries,stock:queries.stock+'&draft=private'},{...queries,attention:queries.attention.replace('as_of_utc=123','as_of_utc=-1')},
    {...queries,attention:queries.attention+'&as_of_utc=124'},
    {...queries,stock:'/api/v1/inventory/stock?limit=200&cursor='+encodeURIComponent(JSON.stringify({...stockCursor,body:'private'}))},
    {...queries,attention:'/api/v1/inventory/attention?limit=200&as_of_utc=123&cursor='+encodeURIComponent(JSON.stringify(stockCursor))}])assert.equal(inventoryCollectionQueries(invalid),null);
  const history=new NavigationHistory();const state={route:'/inventory',filterFingerprint:'a'.repeat(64),activeId:null,selectedId:null,memberIds:[],scrollAnchor:null,focusToken:null,inventoryQueries:queries};
  const token=history.remember(state);queries.stock='changed';assert.notEqual(history.restore(token).inventoryQueries.stock,'changed');
  assert.throws(()=>history.remember({...history.restore(token),route:'/objectives'}));
});

test('Infrastructure return intent fences complete owner cursors, opened identities and nested bounded activity context',()=>{
  const id='11111111-1111-4111-8111-111111111111';
  const query='/api/v1/infrastructure/tree?limit=200';
  const cursor={version:1,query_id:'InfrastructureExplorerQuery',sort_registry_id:'InfrastructureExplorerQuery_ORDER_V1',last_key_tuple:[null,id,4,id],filter_fingerprint:'a'.repeat(64),null_order:'NULLS_LAST'};
  const explorer=query+'&cursor='+encodeURIComponent(JSON.stringify(cursor));
  assert.deepEqual(infrastructureQuery(explorer,'explorer'),{cursor});
  const intent={explorer,openedId:id,tab:'Workbook Activity',components:`/api/v1/infrastructure/network-elements/${id}/components?limit=200`,
    history:`/api/v1/infrastructure/history?target_kind=network_element&target_id=${id}&limit=5`,
    workbook:{history:'/api/v1/infrastructure/workbooks/history?limit=200',run:`/api/v1/infrastructure/workbooks/runs/${id}?limit=200`,proposalId:id,candidatePage:2}};
  assert.equal(infrastructureIntent(intent),intent);
  for(const invalid of [{...intent,body:'copied fact'},{...intent,openedId:'invalid'},{...intent,tab:'Unknown'},{...intent,history:intent.history+'&body=private'},
    {...intent,components:intent.components.replace(id,'22222222-2222-4222-8222-222222222222')},
    {...intent,workbook:{...intent.workbook,body:'private'}},{...intent,workbook:{...intent.workbook,candidatePage:3}},
    {...intent,workbook:{...intent.workbook,run:null}},{...intent,workbook:{...intent.workbook,proposalId:null}},
    {...intent,workbook:null}])assert.equal(infrastructureIntent(invalid),null);
  for(const change of [{...cursor,body:'private'},{...cursor,version:2},{...cursor,query_id:'InstalledComponentQuery'},
    {...cursor,null_order:'NOT_APPLICABLE'},{...cursor,last_key_tuple:[id,4,id]},
    {...cursor,last_key_tuple:[null,id,6,id]},{...cursor,last_key_tuple:[null,'bad',4,id]}])assert.equal(infrastructureQuery(query+'&cursor='+encodeURIComponent(JSON.stringify(change)),'explorer'),null);
  for(const invalid of [query+'&limit=200',query+'&draft=private',query+'#fragment',query+'&cursor=invalid',query+'&cursor='+encodeURIComponent(JSON.stringify('x'.repeat(4096)))])assert.equal(infrastructureQuery(invalid,'explorer'),null);
  const history=new NavigationHistory();const state={route:'/infrastructure',filterFingerprint:'a'.repeat(64),activeId:null,selectedId:null,memberIds:[],focusToken:null,scrollAnchor:null,infrastructure:intent};
  const token=history.remember(state);intent.explorer='changed';intent.workbook.run='changed';
  assert.equal(history.restore(token).infrastructure.explorer,explorer);assert.notEqual(history.restore(token).infrastructure.workbook.run,'changed');
  assert.throws(()=>history.remember({...history.restore(token),route:'/inventory'}));
});
