import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const manifestPath = path.resolve(here, '../public/manifest.json');

if (!fs.existsSync(manifestPath)) {
  throw new Error('public/manifest.json is required; run bench-harness site-data-snapshot first');
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
if (
  !manifest
  || typeof manifest !== 'object'
  || typeof manifest.generatedAt !== 'string'
  || !Array.isArray(manifest.entries)
) {
  throw new Error('public/manifest.json is not a site-data snapshot DTO');
}
