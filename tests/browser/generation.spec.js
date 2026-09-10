import { test } from '@playwright/test';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));

test('isolated public generation selection', async ({ browserName }) => {
  test.skip(browserName !== 'chromium', 'Generation fixture targets Chromium only.');
  test.setTimeout(300_000);
  let child, timer, forceTimer;
  const terminate = signal => {
    if (!child?.pid) return;
    try {
      if (process.platform === 'win32') child.kill(signal);
      else process.kill(-child.pid, signal);
    } catch (error) {
      if (error.code !== 'ESRCH') throw error;
    }
  };
  try {
    await new Promise((resolve, reject) => {
      child = execFile(process.env.PYTHON || join(root, '.venv/bin/python'), [
        '-u', 'tests/browser/run_generation.py',
      ], {
        cwd: root, env: process.env,
        detached: process.platform !== 'win32',
        timeout: 270_000, killSignal: 'SIGTERM', maxBuffer: 16 * 1024 * 1024,
      }, (error, stdout, stderr) => {
        if (stdout) console.log(stdout);
        if (stderr) console.error(stderr);
        if (error) reject(error);
        else resolve();
      });
      timer = setTimeout(() => {
        terminate('SIGTERM');
        forceTimer = setTimeout(() => terminate('SIGKILL'), 5_000);
      }, 270_000);
    });
  } finally {
    clearTimeout(timer);
    clearTimeout(forceTimer);
    terminate('SIGKILL');
  }
});
