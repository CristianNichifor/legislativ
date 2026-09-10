import { defineConfig } from '@playwright/test';
const port = Number(process.env.BROWSER_STATIC_PORT || 5191);

export default defineConfig({
  testDir: './tests/browser',
  testMatch: 'static.spec.js',
  timeout: 180_000,
  expect: { timeout: 90_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  outputDir: 'test-results-static',
  use: { baseURL: `http://127.0.0.1:${port}`, trace: 'retain-on-failure' },
  projects: ['chromium', 'firefox', 'webkit'].map(browserName => ({
    name: browserName, use: { browserName },
  })),
  webServer: {
    command: 'python3 tests/browser/serve_static.py',
    url: `http://127.0.0.1:${port}`, timeout: 120_000, reuseExistingServer: false,
  },
});
