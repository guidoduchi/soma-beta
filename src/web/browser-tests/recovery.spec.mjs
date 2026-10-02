import {test, expect} from '@playwright/test';

test('LLD10-T020 stale review is fenced to the shown recovery generation and accepted owner revision', async ({page}) => {
  await page.goto('/static/ui/fixtures/recovery.html');
  const reviewed=page.getByRole('checkbox'); const reapply=page.getByRole('button',{name:'Reapply reviewed changes'});
  await expect(reapply).toBeDisabled(); await reviewed.check(); await expect(reapply).toBeEnabled();
  await page.getByRole('button',{name:'Refresh current owner revision'}).click();
  await expect(reviewed).not.toBeChecked(); await expect(reapply).toBeDisabled();
  await reviewed.check(); await page.getByRole('button',{name:'Refresh recovery generation'}).click();
  await expect(reviewed).not.toBeChecked(); await expect(reapply).toBeDisabled();
  await expect(page.getByText('Unsaved restores:')).toContainText('0');
  await reviewed.check(); await reapply.click(); await expect(page.getByText('Unsaved restores:')).toContainText('1');
});

test('late discard failure cannot label a freshly queried recovery generation as failed', async ({page}) => {
  await page.clock.install(); await page.goto('/static/ui/fixtures/recovery.html');
  const discard=page.getByRole('button',{name:'Discard recovery copy'}); const reviewed=page.getByRole('checkbox');
  await reviewed.check(); await discard.click(); await expect(discard).toBeDisabled(); await expect(reviewed).toBeDisabled();
  await page.getByRole('button',{name:'Refresh recovery generation'}).click(); await page.clock.runFor(100);
  await expect(discard).toBeEnabled(); await expect(page.getByText('Discard failed.',{exact:false})).toHaveCount(0);
  await expect(reviewed).not.toBeChecked(); await expect(page.getByText('Discard attempts:')).toContainText('1');
  await discard.click(); await page.clock.runFor(100); await expect(page.getByRole('alert').filter({hasText:'Discard failed.'})).toBeVisible();
  await expect(page.getByText('Unsaved restores:')).toContainText('0');
});
