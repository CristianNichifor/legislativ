import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: 'test-results',
  use: { baseURL: 'http://127.0.0.1:5190', trace: 'retain-on-failure' },
  projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({
    name: browserName, use: { browserName },
  })),
  webServer: {
    command: 'PYTHONPATH=. python3 tests/browser/serve.py',
    url: 'http://127.0.0.1:5190', reuseExistingServer: false,
  },
});
