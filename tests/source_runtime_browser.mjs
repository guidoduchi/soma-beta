// Real encrypted source host only: no Vite host, fixture routes or API mocks.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../src/web/package.json', import.meta.url));
const {chromium, expect} = require('@playwright/test');
const {origin, password, browserPath} = JSON.parse(readFileSync(0, 'utf8'));
const manifest = JSON.parse(readFileSync(new URL('../src/soma/ui/static/manifest.json', import.meta.url))).files;
const browser = await chromium.launch({headless: true, executablePath: browserPath});
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [], resources = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    const name = new URL(response.url()).pathname.replace(/^\/static\/ui\//, '');
    if (!name.startsWith('assets/') || !manifest[name]) return;
    resources.push((async () => {
      assert.equal(response.status(), 200);
      const mime = name.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8';
      assert.equal(response.headers()['content-type'], mime);
      const bytes = await response.body();
      assert.equal(createHash('sha256').update(bytes).digest('hex'), manifest[name].sha256);
      return {name, mime, sha256: manifest[name].sha256};
    })());
  });
  await page.goto(origin, {waitUntil: 'domcontentloaded'});
  await expect(page.locator('#submit')).toBeEnabled();
  await page.locator('#password').fill(password);
  await page.locator('#submit').click();
  await expect(page.locator('#main-content')).toBeVisible();
  assert.ok(await page.locator('#root > *').count() > 0);
  const verified = await Promise.all(resources);
  assert.ok(verified.some(resource => resource.name.endsWith('.js')));
  assert.ok(verified.some(resource => resource.name.endsWith('.css')));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({login_completed: true, react_mounted: true, resources: verified}));
} finally {
  await browser.close();
}
