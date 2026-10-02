import {test, expect} from '@playwright/test';

test('Settings consumes owner Objective timezone default without persisting or changing global chronology', async ({page}) => {
  const requests=[];
  await page.route('**/api/v1/settings/objective-timezone', route => {
    requests.push(route.request().method()); return route.fulfill({json:{iana_timezone:'America/Guayaquil',source:'DEFAULT',revision:null}});
  });
  await page.goto('http://127.0.0.1:4174/settings');
  const settings=page.getByRole('region',{name:'Objective scheduling settings'});
  await expect(settings.getByText('Scheduling timezone:',{exact:false})).toContainText('America/Guayaquil. Source: DEFAULT; revision: Default');
  await expect(settings.getByText('Accepted UTC plans',{exact:false})).toBeVisible();
  await expect(settings.getByText('Ordinary application and SLA chronology',{exact:false})).toContainText('America/Guayaquil');
  expect(requests).toEqual(['GET']);
});

test('Settings preserves exact persisted Objective timezone revision and rejects an inconsistent default revision', async ({page}) => {
  let invalid=false;
  await page.route('**/api/v1/settings/objective-timezone', route => route.fulfill({json:invalid
    ? {iana_timezone:'Asia/Tokyo',source:'DEFAULT',revision:4}
    : {iana_timezone:'Asia/Tokyo',source:'PERSISTED',revision:4}}));
  await page.goto('http://127.0.0.1:4174/settings');
  const settings=page.getByRole('region',{name:'Objective scheduling settings'});
  await expect(settings.getByText('Scheduling timezone:',{exact:false})).toContainText('Asia/Tokyo. Source: PERSISTED; revision: 4');
  invalid=true;await page.reload();
  await expect(settings.getByRole('alert')).toContainText('owner projection could not be rendered');
  await expect(settings.getByText('Scheduling timezone:',{exact:false})).toHaveCount(0);
});
