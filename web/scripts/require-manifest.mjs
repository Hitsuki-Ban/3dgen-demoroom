import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const manifestPath = path.resolve(here, '../public/manifest.json');

export function requireManifest(inputPath, { rejectPartial }) {
  if (!fs.existsSync(inputPath)) {
    throw new Error('public/manifest.json is required; run bench-harness site-data-snapshot first');
  }

  const manifest = JSON.parse(fs.readFileSync(inputPath, 'utf-8'));
  if (
    !manifest
    || typeof manifest !== 'object'
    || typeof manifest.generatedAt !== 'string'
    || typeof manifest.partial !== 'boolean'
    || !Array.isArray(manifest.entries)
  ) {
    throw new Error('public/manifest.json is not a site-data snapshot DTO');
  }

  if (manifest.partial) {
    if (rejectPartial) {
      throw new Error('partial site-data manifest cannot be used for a production build');
    }
    console.warn('WARNING: using a partial site-data manifest for frontend development');
  }

  return manifest;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (invokedPath === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.some((argument) => argument !== '--reject-partial') || args.length > 1) {
    throw new Error('usage: node scripts/require-manifest.mjs [--reject-partial]');
  }
  requireManifest(manifestPath, { rejectPartial: args[0] === '--reject-partial' });
}
