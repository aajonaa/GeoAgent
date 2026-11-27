import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(rootDir, '../../geological_agent/team/web');

const jsFiles = fs
  .readdirSync(webDir)
  .filter((name) => name.endsWith('.js'))
  .sort();

let checked = 0;
for (const name of jsFiles) {
  const full = path.join(webDir, name);
  execFileSync(process.execPath, ['--check', full], { stdio: 'inherit' });
  checked += 1;
}

const bundleFile = path.join(webDir, 'bundles', 'core-bridge.js');
if (fs.existsSync(bundleFile)) {
  execFileSync(process.execPath, ['--check', bundleFile], { stdio: 'inherit' });
  checked += 1;
}

console.log(`Syntax check passed for ${checked} JavaScript files.`);
