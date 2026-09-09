import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  testMatch: 'static.spec.js',
  timeout: 180_000,
  expect: { timeout: 90_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: 'test-results-static',
  use: { baseURL: 'http://127.0.0.1:5191', trace: 'retain-on-failure' },
  projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({
    name: browserName, use: { browserName },
  })),
  webServer: {
    command: 'python3 tests/browser/serve_static.py',
    url: 'http://127.0.0.1:5191', timeout: 120_000, reuseExistingServer: false,
  },
});
