import {test, expect} from '@playwright/test';

async function mount(page) {
  await page.goto('/static/ui/fixtures/governed.html?state=empty');
  await page.evaluate(async () => {
    const {default:React} = await import('/static/ui/node_modules/.vite/deps/react.js');
    const {default:client} = await import('/static/ui/node_modules/.vite/deps/react-dom_client.js');
    const {CommunicationPanel} = await import('/static/ui/components/CommunicationPanel.tsx');
    const node = document.createElement('div'); node.id = 'panel-regression'; document.body.append(node);
    const root = client.createRoot(node); const requests = [];
    const query = (type, id, cursor, limit, signal) => new Promise(resolve => requests.push({type,id,cursor,limit,signal,resolve}));
    const render = id => root.render(React.createElement(CommunicationPanel, {targetType:'SERVICE_REQUEST',targetId:id,query,openMessage:()=>{}}));
    const projection = (id, subject, terminal = false) => ({summary:{target_type:'SERVICE_REQUEST',target_id:id,
      received_count:1,sent_count:0,unknown_count:0,last_interaction:{known:false,utc_epoch_seconds:null,source_kind:'UNKNOWN'},
      last_direction:'UNKNOWN',pending_proposals:0,coverage_state:'UNKNOWN',warnings:['Synthetic owner summary warning'],body_navigation_available:true},
      recent_messages:{items:[{communication_id:'synthetic-message',subject,direction:'UNKNOWN',content_state:'RETAINED',
        chronology:{known:false,utc_epoch_seconds:null,source_kind:'UNKNOWN'}}],next_cursor:null},terminal_frozen:terminal,warnings:[]});
    window.panelRegression = {requests,render,projection}; render('synthetic-A');
  });
  await expect.poll(()=>page.evaluate(()=>window.panelRegression.requests.length)).toBe(1);
}

test('terminal panel denies body navigation and preserves summary warnings', async ({page}) => {
  await mount(page);
  await page.evaluate(()=>{const t=window.panelRegression;const value=t.projection('synthetic-A','Synthetic terminal message',true);
    value.summary.last_interaction={known:true,utc_epoch_seconds:1790812800,source_kind:'RECEIVED_TIME'};t.requests[0].resolve(value);});
  const panel=page.locator('#panel-regression');
  await expect(panel.getByText('Synthetic terminal message',{exact:false})).toBeVisible();
  await expect(panel.getByText('Synthetic owner summary warning')).toBeVisible();
  await expect(panel.getByText('Last supported interaction:',{exact:false})).toContainText('UTC epoch seconds 1790812800');
  await expect(panel.getByRole('button',{name:'Open canonical message'})).toHaveCount(0);
});

test('communication target switch aborts old reads and rejects their late response', async ({page}) => {
  await mount(page);
  await page.evaluate(()=>window.panelRegression.render('synthetic-B'));
  await expect.poll(()=>page.evaluate(()=>window.panelRegression.requests.length)).toBe(2);
  expect(await page.evaluate(()=>window.panelRegression.requests[0].signal.aborted)).toBe(true);
  await page.evaluate(()=>{const t=window.panelRegression;t.requests[1].resolve(t.projection('synthetic-B','Synthetic current message'));});
  const panel=page.locator('#panel-regression'); await expect(panel.getByText('Synthetic current message',{exact:false})).toBeVisible();
  await expect(panel.getByText('Last supported interaction: Unknown')).toBeVisible();
  await page.evaluate(()=>{const t=window.panelRegression;t.requests[0].resolve(t.projection('synthetic-A','Synthetic obsolete message'));});
  await expect(panel.getByText('Synthetic obsolete message',{exact:false})).toHaveCount(0);
  await expect(panel.getByText('Synthetic current message',{exact:false})).toBeVisible();
});

test('invalid communication counts fail closed without displaying owner evidence', async ({page}) => {
  await mount(page);
  await page.evaluate(()=>{const t=window.panelRegression;const value=t.projection('synthetic-A','Synthetic invalid message');
    value.summary.received_count=-1;t.requests[0].resolve(value);});
  const panel=page.locator('#panel-regression');
  await expect(panel.getByRole('alert')).toContainText('Communication evidence is unavailable');
  await expect(panel.getByText('Synthetic invalid message',{exact:false})).toHaveCount(0);
  await expect(panel.getByText('Received:',{exact:false})).toHaveCount(0);
});
