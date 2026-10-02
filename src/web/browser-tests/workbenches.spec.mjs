import {test, expect} from '@playwright/test';

test('LLD10-T016 T017 T048 F011 reflow and pane/tab changes preserve unsaved intent', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto('/static/ui/fixtures/harness.html');
  await expect(page.getByRole('heading', {name: 'Tickets', exact: true})).toBeVisible();
  await expect(page.getByRole('tab')).toHaveText(['Overview','Devices','Spare Parts','RFCs','Tasks','Notes']);
  await page.getByRole('tab', {name: 'Notes', exact: true}).click();
  await page.getByRole('textbox', {name: 'Unsaved note'}).fill('Synthetic unsaved text');
  await page.setViewportSize({width: 480, height: 900});
  await page.getByRole('button', {name: 'Communications', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('provider unavailable');
  await page.getByRole('button', {name: 'Work', exact: true}).click();
  await expect(page.getByRole('textbox', {name: 'Unsaved note'})).toHaveValue('Synthetic unsaved text');
  await expect(page.getByText('Unsaved UI changes')).toBeVisible();
  await expect(page.getByText('Domain Draft — accepted state')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
test('LLD10-T008 T010 T011 autocomplete disclosure and keyboard are bounded and explicit', async ({page}) => {
  await page.goto('/static/ui/fixtures/harness.html');
  const input = page.getByRole('combobox'); await input.focus();
  await expect(page.getByRole('option')).toHaveCount(0);
  await input.fill('a'); await page.waitForTimeout(200); await expect(page.getByRole('option')).toHaveCount(0);
  await input.fill('ab'); await expect(page.getByRole('option')).toHaveCount(25);
  await input.press('ArrowDown'); await input.press('Tab'); await expect(page.getByText('Accepted option:')).toContainText('none');
  await page.getByRole('button', {name: 'More options'}).click(); await expect(page.getByRole('option')).toHaveCount(50);
  await expect(page.getByText('More results exist. Refine your search.')).toBeVisible();
  await input.focus(); await input.press('Escape'); await expect(page.getByRole('listbox')).toHaveCount(0);
});
test('LLD10-T043 T044 modal isolates background, starts safely and restores focus', async ({page}) => {
  await page.goto('/static/ui/fixtures/harness.html');
  const invoker = page.getByRole('button', {name: 'Review synthetic action'}); await invoker.click();
  await expect(page.getByRole('dialog')).toBeVisible(); await expect(page.getByRole('button', {name: 'Cancel', exact: true})).toBeFocused();
  expect(await page.evaluate(() => document.querySelector('.soma-shell').parentElement.inert)).toBeTruthy();
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0); await expect(invoker).toBeFocused();
  await expect(page.getByText('Commands:')).toContainText('0');
});
test('LLD10-T018 T034 T036 T051 T055 F019 F025 safe text, bounded rows and visible owner blockers', async ({page}) => {
  await page.setViewportSize({width: 900, height: 900}); await page.goto('/static/ui/fixtures/harness.html');
  await expect(page.getByRole('button', {name: 'Blocked owner action'})).toBeDisabled();
  await expect(page.getByRole('button', {name: 'Unknown owner action'})).toBeDisabled();
  await expect(page.getByText('Synthetic dependency exists. Review dependencies.')).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(200); await expect(page.getByRole('button', {name: 'Next page'})).toBeVisible();
  expect(await page.evaluate(() => window.FORBIDDEN_MARKER)).toBeUndefined();
  await page.evaluate(() => {document.documentElement.style.fontSize = '28px';});
  await expect(page.getByRole('button', {name: 'Review synthetic action'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
test('LLD10-T013 T014 T035 deliberate hold cancels on release and scroll and submits only once', async ({page}) => {
  await page.goto('/static/ui/fixtures/harness.html');
  const button = page.getByRole('button', {name: 'Hold synthetic delete'});
  await button.focus(); await page.keyboard.down('Space'); await page.waitForTimeout(150); await page.keyboard.up('Space');
  await expect(page.getByText('Commands:')).toContainText('0');
  await page.keyboard.down('Space'); await page.waitForTimeout(150);
  await page.evaluate(() => window.dispatchEvent(new Event('soma-scroll-gesture')));
  await page.keyboard.up('Space'); await expect(page.getByText('Commands:')).toContainText('0');
  await page.emulateMedia({reducedMotion: 'reduce', forcedColors: 'active'});
  await button.focus(); await page.keyboard.down('Space');
  await expect(page.getByText('Commands:')).toContainText('1', {timeout: 5000});
  await page.keyboard.up('Space'); await button.click(); await expect(page.getByText('Commands:')).toContainText('1');
});
test('LLD10-T005 T006 T007 hovered scroll owner cannot chain into sibling evidence', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 900}); await page.goto('/static/ui/fixtures/harness.html');
  const work = page.getByRole('region', {name: 'Operational work'});
  await work.evaluate(node => {node.scrollTop = node.scrollHeight;});
  const before = await page.locator('.communication-pane').evaluate(node => node.scrollTop);
  await work.hover(); await page.mouse.wheel(0, 1000);
  expect(await page.locator('.communication-pane').evaluate(node => node.scrollTop)).toBe(before);
  await expect(page.getByText('Commands:')).toContainText('0');
});
test('LLD10-T045 F023 modal preserves input on failure and restores a removed invoker to the logical container', async ({page}) => {
  await page.goto('/static/ui/fixtures/harness.html');
  await page.getByRole('button', {name: 'Review synthetic action'}).click();
  const input = page.getByRole('textbox', {name: 'Review reason'}); await input.fill('Synthetic retained review');
  await page.getByRole('button', {name: 'Inject validation failure'}).click();
  await expect(input).toHaveValue('Synthetic retained review'); await expect(input).toBeFocused();
  await page.getByRole('button', {name: 'Remove synthetic invoker'}).click(); await page.keyboard.press('Escape');
  await expect(page.locator('#main-content')).toBeFocused(); await expect(page.getByText('Commands:')).toContainText('0');
});
test('unsupported browser capabilities render a bounded unavailable state before interactions', async ({page}) => {
  await page.addInitScript(() => {delete window.ResizeObserver;});
  await page.goto('/static/ui/fixtures/harness.html');
  await expect(page.getByRole('alert')).toContainText('UI_BROWSER_CAPABILITY_UNSUPPORTED');
  await expect(page.getByRole('button', {name: 'Hold synthetic delete'})).toHaveCount(0);
});
