import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { requireManifest } from './require-manifest.mjs';


function writeManifest(directory, manifest) {
  const manifestPath = path.join(directory, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest));
  return manifestPath;
}


test('accepts a complete snapshot without warning', (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'manifest-contract-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifestPath = writeManifest(directory, {
    generatedAt: '2026-07-11T00:00:00Z',
    partial: false,
    entries: [],
  });

  assert.equal(requireManifest(manifestPath, { rejectPartial: true }).partial, false);
});


test('warns when development uses an explicit partial snapshot', (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'manifest-contract-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifestPath = writeManifest(directory, {
    generatedAt: '2026-07-11T00:00:00Z',
    partial: true,
    entries: [{}],
  });
  const warnings = [];
  const originalWarn = console.warn;
  console.warn = (message) => warnings.push(message);
  context.after(() => { console.warn = originalWarn; });

  assert.equal(requireManifest(manifestPath, { rejectPartial: false }).partial, true);
  assert.deepEqual(warnings, ['WARNING: using a partial site-data manifest for frontend development']);
});


test('rejects partial snapshots for production builds', (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'manifest-contract-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifestPath = writeManifest(directory, {
    generatedAt: '2026-07-11T00:00:00Z',
    partial: true,
    entries: [{}],
  });

  assert.throws(
    () => requireManifest(manifestPath, { rejectPartial: true }),
    /partial site-data manifest cannot be used for a production build/,
  );
});


test('rejects snapshots without an explicit partial marker', (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'manifest-contract-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const manifestPath = writeManifest(directory, {
    generatedAt: '2026-07-11T00:00:00Z',
    entries: [],
  });

  assert.throws(
    () => requireManifest(manifestPath, { rejectPartial: false }),
    /not a site-data snapshot DTO/,
  );
});
