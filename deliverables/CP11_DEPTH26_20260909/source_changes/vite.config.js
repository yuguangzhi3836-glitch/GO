// Development-only adapter: all GO routes use the existing Python application.
// The supervised preview owns the lifetime of both Vite and this isolated API.
import { defineConfig } from 'vite';
import { spawn } from 'node:child_process';
import { chmodSync, mkdirSync, openSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomBytes } from 'node:crypto';

export default defineConfig({
  server: {
    allowedHosts: ['terminal.local'],
    proxy: { '^/(go-app|go-admin|supplier-console|console-assets|v1|health|ready|metrics)': 'http://127.0.0.1:4174' },
  },
  plugins: [{
    name: 'go-isolated-review-api',
    async configureServer(server) {
      const root = process.cwd();
      const state = resolve(root, '.preview');
      mkdirSync(state, { recursive: true });
      const python = resolve(root, 'gate_runtime/python/bin/python');
      chmodSync(python, 0o755);
      const log = openSync(resolve(state, 'api.log'), 'a');
      const child = spawn(python, ['scripts/preview_api.py'], {
        cwd: root, stdio: ['ignore', log, log],
        env: { PATH: process.env.PATH, PYTHONPATH: resolve(root, 'src'),
          APP_ENV: 'local', GO_PREVIEW_ONLY: '1', DATABASE_URL: `sqlite+pysqlite:///${state}/review.db`,
          VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED: 'false', HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED: 'false',
          JWT_SIGNING_KEY: randomBytes(32).toString('hex'),
          BOOTSTRAP_ADMIN_PASSWORD: randomBytes(24).toString('hex'),
          BOOTSTRAP_SUPPLIER_PASSWORD: randomBytes(24).toString('hex'),
        },
      });
      const stop = () => { if (!child.killed) child.kill('SIGTERM'); };
      server.httpServer?.once('close', stop);
      process.once('exit', stop);
      let failure;
      child.once('error', error => { failure = error; });
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        if (failure || child.exitCode !== null) throw failure || new Error('GO preview API exited; inspect .preview/api.log');
        try { if ((await fetch('http://127.0.0.1:4174/go-app/', { signal: AbortSignal.timeout(1000) })).ok) return; } catch {}
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      stop();
      throw new Error('GO preview API readiness exceeded 30 seconds; inspect .preview/api.log');
    },
  }],
});
