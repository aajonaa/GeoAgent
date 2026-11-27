import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vitest/config';

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(rootDir, '../geological_agent/team/web/bundles');

function bundleIntegrityManifest(): Plugin {
  return {
    name: 'orebogao-bundle-manifest',
    apply: 'build',
    closeBundle() {
      if (!fs.existsSync(outDir)) return;
      const files: Record<string, { size: number; sha256: string }> = {};
      for (const name of fs.readdirSync(outDir).sort()) {
        if (name === 'bundles-manifest.json') continue;
        const full = path.join(outDir, name);
        if (!fs.statSync(full).isFile()) continue;
        const raw = fs.readFileSync(full);
        files[name] = {
          size: raw.length,
          sha256: crypto.createHash('sha256').update(raw).digest('hex'),
        };
      }
      const manifest = {
        schema: 1,
        entry: 'core-bridge.js',
        globalNamespace: 'OreBogaoCore',
        migratedGlobals: [
          'GeoPresentationState',
          'OreSageDrafts',
          'GeoAgentRecovery',
          'GeoAgentPlan',
        ],
        cspSafe: true,
        files,
      };
      fs.writeFileSync(
        path.join(outDir, 'bundles-manifest.json'),
        JSON.stringify(manifest, null, 2) + '\n',
        'utf-8',
      );
    },
  };
}

export default defineConfig({
  root: rootDir,
  plugins: [bundleIntegrityManifest()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:50014',
      '/assets': 'http://127.0.0.1:50014',
      '/vendor': 'http://127.0.0.1:50014',
      '/knowledge-graph-assets': 'http://127.0.0.1:50014',
      '/knowledge-corpus-assets': 'http://127.0.0.1:50014',
      '/data-inventory-assets': 'http://127.0.0.1:50014',
      '/case-assets': 'http://127.0.0.1:50014',
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    sourcemap: true,
    target: 'es2022',
    minify: 'esbuild',
    lib: {
      entry: path.resolve(rootDir, 'src/main.ts'),
      name: 'OreBogaoCore',
      formats: ['iife'],
      fileName: () => 'core-bridge.js',
    },
    rollupOptions: {
      output: {
        extend: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts'],
  },
});
