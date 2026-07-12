import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { validateWranglerConfig } from './validate-wrangler-config.mjs';


const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url));
const wranglerConfigPath = path.resolve(scriptsDirectory, '..', 'wrangler.jsonc');


function writeMutatedConfig(context, mutate) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'wrangler-contract-'));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const target = path.join(directory, 'wrangler.jsonc');
  fs.writeFileSync(target, mutate(fs.readFileSync(wranglerConfigPath, 'utf8')));
  return target;
}


test('accepts the production routing contract', () => {
  assert.doesNotThrow(() => validateWranglerConfig(wranglerConfigPath));
});


test('rejects disabling the existing workers.dev URL', (context) => {
  const target = writeMutatedConfig(context, (source) => source.replace('"workers_dev": true', '"workers_dev": false'));
  assert.throws(() => validateWranglerConfig(target), /keep workers_dev enabled/);
});


test('rejects enabling implicit preview URLs', (context) => {
  const target = writeMutatedConfig(context, (source) => source.replace('"preview_urls": false', '"preview_urls": true'));
  assert.throws(() => validateWranglerConfig(target), /keep preview URLs disabled/);
});


test('rejects a different or additional Custom Domain route', (context) => {
  const differentTarget = writeMutatedConfig(context, (source) => source.replace(
    '"pattern": "3dgen.hitsuki.space"',
    '"pattern": "*.hitsuki.space"',
  ));
  const additionalTarget = writeMutatedConfig(context, (source) => source.replace(
    '"routes": [',
    '"routes": [{ "pattern": "preview.hitsuki.space", "custom_domain": true },',
  ));

  assert.throws(() => validateWranglerConfig(differentTarget), /only the exact 3dgen\.hitsuki\.space/);
  assert.throws(() => validateWranglerConfig(additionalTarget), /only the exact 3dgen\.hitsuki\.space/);
});
