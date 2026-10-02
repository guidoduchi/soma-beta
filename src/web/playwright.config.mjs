import {defineConfig} from '@playwright/test';
export default defineConfig({testDir: './browser-tests', workers: 1, reporter: 'list', outputDir: '../../tmp/lld10-browser-results',
  use: {baseURL: 'http://127.0.0.1:4173', headless: true, timezoneId: 'UTC',
    launchOptions: {executablePath: process.env.SOMA_TEST_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}},
  webServer: process.env.SOMA_TEST_EXTERNAL_SERVER === '1' ? undefined :
    {command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173/static/ui/fixtures/harness.html', reuseExistingServer: false}});
