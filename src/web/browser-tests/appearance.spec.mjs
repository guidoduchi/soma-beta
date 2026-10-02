import {test, expect} from '@playwright/test';

async function settings(page) {
  await page.route('**/api/v1/settings/ui.*', route => {
    const key = new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({json:{setting_key:key,value:key === 'ui.skin_id' ? 'soma_core' : 'system',revision:null,
      source:'DEFAULT',contract_name:key+'.v1',contract_version:1,semantic_owner:'LLD-10'}});
  });
}
test('appearance preview failure restores both accepted axes and requires refresh', async ({page}) => {
  await settings(page); await page.emulateMedia({colorScheme:'light'});
  await page.goto('/static/ui/fixtures/appearance.html');
  const mode = page.getByLabel('Color mode'); await expect(mode).toBeEnabled();
  await mode.selectOption('dark'); await expect(page.getByRole('alert')).toContainText('Accepted appearance has been restored');
  await expect(page.locator('html')).toHaveAttribute('data-mode','light'); await expect(mode).toHaveValue('system');
  await expect(mode).toBeDisabled(); await page.getByRole('button', {name:'Refresh appearance'}).click(); await expect(mode).toBeEnabled();
  await expect(page.getByLabel('Skin')).toHaveValue('soma_core');
});
test('compiled appearance reads owner defaults and system changes while unrelated work stays available', async ({page}) => {
  await settings(page); await page.emulateMedia({colorScheme:'light'});
  await page.goto('http://127.0.0.1:4174/settings/appearance');
  await expect(page.getByLabel('Color mode')).toHaveValue('system');
  await expect(page.getByLabel('Color mode')).toBeDisabled();
  await page.emulateMedia({colorScheme:'dark'}); await expect(page.locator('html')).toHaveAttribute('data-mode','dark');
  await page.getByRole('link', {name:'Tickets',exact:true}).click();
  await page.emulateMedia({colorScheme:'light'}); await expect(page.locator('html')).toHaveAttribute('data-mode','light');
});
