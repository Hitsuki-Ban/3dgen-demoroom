import assert from 'node:assert/strict';
import test from 'node:test';

import { DEFAULT_BASE_URL, parseArgs } from './capture-screenshots.mjs';

test('uses the canonical production URL by default', () => {
  assert.deepEqual(parseArgs([]), { baseUrl: DEFAULT_BASE_URL });
});

test('accepts one explicit local base URL', () => {
  assert.deepEqual(parseArgs(['--base-url', 'http://127.0.0.1:5173']), {
    baseUrl: 'http://127.0.0.1:5173/',
  });
});

test('rejects missing, unknown, authenticated, or stateful URLs', () => {
  assert.throws(() => parseArgs(['--base-url']), /requires a value/);
  assert.throws(() => parseArgs(['--output-dir', 'tmp']), /unknown argument/);
  assert.throws(() => parseArgs(['--base-url', 'ftp://example.com']), /unauthenticated HTTP\(S\)/);
  assert.throws(() => parseArgs(['--base-url', 'https://user@example.com']), /unauthenticated HTTP\(S\)/);
  assert.throws(() => parseArgs(['--base-url', 'https://example.com/?draft=1']), /query string or fragment/);
});
