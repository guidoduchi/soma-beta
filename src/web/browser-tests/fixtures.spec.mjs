import {readFileSync, writeFileSync} from 'node:fs';
import {test, expect} from '@playwright/test';
const manifest = JSON.parse(readFileSync(new URL('../fixtures/manifest.json', import.meta.url), 'utf8'));

for (const fixture of manifest.fixtures) {
  test(`LLD10-T052 ${fixture.fixture_id} governed responsive semantic state`, async ({page, browser}, testInfo) => {
    const state = fixture['surface/state'];
    await page.setViewportSize({width: fixture.container_width_css_px, height: fixture.viewport_height_css_px});
    await page.emulateMedia({colorScheme:'light', reducedMotion:'reduce', forcedColors:'none'});
    await page.clock.install({time: new Date(fixture.deterministic_clock)});
    await page.clock.pauseAt(new Date(fixture.deterministic_clock));
    if (state === 'loading' || state === 'error') {
      await page.route('**/api/v1/tickets/service-requests/*', async route => {
        if (state === 'error') await route.fulfill({status:503,json:{code:'SYNTHETIC_OWNER_UNAVAILABLE'}});
        else await new Promise(resolve => page.once('close', resolve));
      });
    }
    await page.goto(`/static/ui/fixtures/governed.html?state=${state}`);
    await page.evaluate(() => {document.documentElement.dataset.mode='light'; document.documentElement.dataset.skin='soma_core';});
    await page.clock.runFor(100);
    await expect(page.getByRole('heading', {name:`Synthetic ${state} fixture`,exact:true})).toBeVisible();
    await expect(page.getByRole('tab')).toHaveText(['Overview','Devices','Spare Parts','RFCs','Tasks','Notes']);
    if (state === 'empty') await expect(page.getByText('No accepted records in this synthetic owner page.')).toBeVisible();
    if (state === 'loading') await expect(page.getByRole('status').filter({hasText:'Loading accepted state.'})).toBeVisible();
    if (state === 'error') {
      await expect(page.getByRole('alert')).toContainText('owning query is unavailable');
      await expect(page.getByRole('button', {name:'Retry accepted state'})).toBeEnabled();
    }
    if (state === 'warning') await expect(page.getByRole('button', {name:'Synthetic blocked action'})).toBeDisabled();
    if (state === 'stale' || state === 'working-copy-recovery') {
      await expect(page.getByRole('heading', {name:'Accepted current values'})).toBeVisible();
      await expect(page.getByRole('heading', {name:'Unsaved working-copy values'})).toBeVisible();
      const restore = page.getByRole('button', {name:state === 'stale' ? 'Reapply reviewed changes' : 'Restore as unsaved changes'});
      if (state === 'stale') await expect(restore).toBeDisabled(); else await expect(restore).toBeEnabled();
    }
    if (state === 'destructive-preview') {
      await expect(page.getByRole('region', {name:'Complete selected-target impact'})).toContainText('5 selected targets reviewed');
      for (const outcome of ['ELIGIBLE','NO CHANGE','BLOCKED','CONFLICT','INDETERMINATE']) await expect(page.getByText(`${outcome}: 1`, {exact:true})).toBeVisible();
    }
    if (state === 'historical') {
      if (fixture.container_width_css_px < 1440) await page.getByRole('button', {name:'Communications',exact:true}).click();
      await expect(page.getByText('Historical terminal summary.', {exact:false})).toBeVisible();
      await expect(page.getByRole('button', {name:'Open canonical message'})).toHaveCount(0);
    }
    if (state === 'keyboard-focus') await page.getByRole('button', {name:'Synthetic keyboard target'}).focus();
    if (state === 'autocomplete') {
      await page.getByRole('combobox').fill('sy'); await page.clock.runFor(200);
      await expect(page.getByRole('option')).toHaveCount(2); await expect(page.getByRole('option').last()).toHaveAttribute('aria-disabled','true');
    }
    if (state === 'dialog') {
      await page.getByRole('button', {name:'Open synthetic review'}).click();
      await expect(page.getByRole('button', {name:'Cancel',exact:true})).toBeFocused();
      expect(await page.evaluate(() => document.querySelector('.soma-shell').parentElement.inert)).toBe(true);
    }
    if (state === 'deliberate-hold-progress') {
      await page.getByRole('button', {name:'Hold synthetic destructive action'}).focus(); await page.keyboard.down('Space');
      await page.clock.runFor(1500); await expect(page.getByRole('status').filter({hasText:'Keep holding'})).toBeVisible();
      const progress = await page.getByRole('progressbar').evaluate(node => node.value);
      expect(progress).toBeGreaterThan(0.4); expect(progress).toBeLessThan(0.6);
      await expect(page.getByText('Owner commands:')).toContainText('0');
    }
    if (fixture.expected_focus === 'body') {
      expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
    } else {
      await expect(state === 'autocomplete' ? page.getByRole('combobox') : page.getByRole('button', {name:fixture.expected_focus,exact:true})).toBeFocused();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone)).toBe(fixture.timezone);
    const screenshot = testInfo.outputPath(`${fixture.fixture_id}.png`);
    await page.screenshot({path:screenshot, animations:'disabled'});
    await testInfo.attach('governed-state-render', {path:screenshot,contentType:'image/png'});
    writeFileSync(testInfo.outputPath('execution-context.json'), JSON.stringify({fixture_id:fixture.fixture_id,
      browser_version:browser.version(),platform:process.platform,semantic_assertions:'passed',pixel_baseline:'unapproved'},null,2));
    if (state === 'deliberate-hold-progress') {await page.keyboard.up('Space'); await expect(page.getByText('Owner commands:')).toContainText('0');}
  });
}
