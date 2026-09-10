import { test } from '@playwright/test';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));

test('durable browser workspace', async ({ browserName, baseURL }) => {
  test.skip(browserName !== 'chromium', 'Workspace fixture targets Chromium only.');
  test.setTimeout(300_000);
  let child, timer;
  const terminate = () => {
    if (!child?.pid) return;
    try {
      // The fixture starts Chromium and Python: clean up their process group on failure too.
      if (process.platform === 'win32') child.kill('SIGKILL');
      else process.kill(-child.pid, 'SIGKILL');
    } catch (error) {
      if (error.code !== 'ESRCH') throw error;
    }
  };
  try {
    await new Promise((resolve, reject) => {
      child = execFile(process.execPath, ['tests/browser_workspace.cjs'], {
        cwd: root,
        env: { ...process.env, BROWSER_BASE_URL: baseURL },
        detached: process.platform !== 'win32',
        timeout: 270_000,
        killSignal: 'SIGKILL',
        maxBuffer: 16 * 1024 * 1024,
      }, (error, stdout, stderr) => {
        if (stdout) console.log(stdout);
        if (stderr) console.error(stderr);
        if (error) reject(error);
        else resolve();
      });
      timer = setTimeout(terminate, 270_000);
    });
  } finally {
    clearTimeout(timer);
    terminate();
  }
});
