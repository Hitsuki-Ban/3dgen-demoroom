import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { Readable } from 'node:stream';
import test from 'node:test';

import sharp from 'sharp';

import { assertWebglBackend } from './thumbnail-renderer.mjs';

import {
  evaluateCacheMetadata,
  expectedCacheIdentity,
  expectedThumbnailMetadata,
  listSiteDataObjects,
  parseCliArgs,
  parseModelRegistry,
  parseTasks,
  reconcileInventory,
  renderFingerprint,
  requireR2Environment,
  runThumbnailBatch,
  sha256,
  THUMBNAIL_CACHE_CONTROL,
  thumbnailWriteCondition,
} from './thumbnail-batch-lib.mjs';

const SOURCE_ETAG = 'aabbccddeeff0011';
const THUMB_ETAG = '1122334455667788';
const WEBP_OPTIONS = { quality: 85, alphaQuality: 100, effort: 6, smartSubsample: true };

function object(key, size = 2, etag = '"0011223344556677"') {
  return { key, size, etag };
}

function commandName(command) {
  return command.constructor.name;
}

async function opaqueWebp() {
  return sharp({
    create: {
      width: 320,
      height: 320,
      channels: 4,
      background: { r: 220, g: 80, b: 30, alpha: 1 },
    },
  })
    .webp(WEBP_OPTIONS)
    .toBuffer();
}

test('parseCliArgs requires an exact R2 root and explicit failure matrix', () => {
  const parsed = parseCliArgs([
    's3://3dgen-runs/site-data',
    '--expected-failure',
    'partcrafter/chrome-espresso-machine',
    '--model',
    'triposr',
    '--task',
    'cartoon-apple',
    '--backend',
    'gpu',
    '--check',
    '--report',
    'report.json',
  ]);
  assert.deepEqual(parsed.s3Root, { bucket: '3dgen-runs', prefix: 'site-data' });
  assert.deepEqual([...parsed.expectedFailures], ['partcrafter/chrome-espresso-machine']);
  assert.equal(parsed.model, 'triposr');
  assert.equal(parsed.task, 'cartoon-apple');
  assert.equal(parsed.backend, 'gpu');
  assert.equal(parsed.check, true);
  assert.equal(parsed.report, 'report.json');

  assert.throws(
    () => parseCliArgs(['s3://3dgen-runs/site-data']),
    /explicit --expected-failure/,
  );
  assert.throws(
    () =>
      parseCliArgs([
        's3://3dgen-runs/site-data/',
        '--expected-failure',
        'partcrafter/chrome-espresso-machine',
      ]),
    /must be exactly/,
  );
  assert.throws(
    () =>
      parseCliArgs([
        's3://3dgen-runs/site-data',
        '--expected-failure',
        'partcrafter/chrome-espresso-machine',
        '--check',
        '--force',
      ]),
    /mutually exclusive/,
  );
});

test('R2 credentials require a path-free HTTPS endpoint', () => {
  const credentials = {
    R2_ENDPOINT: 'https://account.r2.cloudflarestorage.com',
    R2_ACCESS_KEY_ID: 'access',
    R2_SECRET_ACCESS_KEY: 'secret',
  };
  assert.equal(requireR2Environment(credentials).endpoint, credentials.R2_ENDPOINT);
  assert.throws(
    () => requireR2Environment({ ...credentials, R2_ENDPOINT: `${credentials.R2_ENDPOINT}/bucket` }),
    /without credentials, path, query, or fragment/,
  );
});

test('registry and task parsers reject unsafe or duplicate IDs', () => {
  assert.deepEqual(parseModelRegistry(['model-a', 'model-b']), ['model-a', 'model-b']);
  assert.deepEqual(parseTasks([{ id: 'task-a' }, { id: 'task-b' }]), ['task-a', 'task-b']);
  assert.throws(() => parseModelRegistry(['model-a', 'model-a']), /duplicate/);
  assert.throws(() => parseTasks([{ id: '../task' }]), /must match/);
});

test('renderer backend identity rejects software fallback and mismatched adapters', () => {
  assert.doesNotThrow(() =>
    assertWebglBackend(
      'gpu',
      'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)',
    ),
  );
  assert.doesNotThrow(() =>
    assertWebglBackend('swiftshader', 'ANGLE (Google, Vulkan (SwiftShader Device), SwiftShader driver)'),
  );
  assert.throws(
    () => assertWebglBackend('gpu', 'ANGLE (Google, Vulkan (SwiftShader Device), SwiftShader driver)'),
    /did not resolve to hardware/,
  );
  assert.throws(
    () => assertWebglBackend('swiftshader', 'ANGLE (NVIDIA, Direct3D11, D3D11)'),
    /unexpected WebGL renderer/,
  );
});

test('reconcileInventory enforces the complete success/failure matrix', () => {
  const inventory = reconcileInventory({
    objects: [
      object('site-data/model-a/task-a/meta.json'),
      object('site-data/model-a/task-a/output.glb', 12, `"${SOURCE_ETAG}"`),
      object('site-data/model-a/task-a/thumb.webp'),
      object('site-data/model-a/task-a/LICENSE'),
      object('site-data/model-a/task-a/raw/intermediate/mesh.obj'),
      object('site-data/model-a/task-b/failure.json'),
    ],
    modelIds: ['model-a'],
    taskIds: ['task-a', 'task-b'],
    expectedFailures: new Set(['model-a/task-b']),
  });
  assert.equal(inventory.successCells.length, 1);
  assert.equal(inventory.failureCells.length, 1);
  assert.equal(inventory.successCells[0].source.etag, SOURCE_ETAG);
  assert.equal(inventory.successCells[0].source.ifMatch, `"${SOURCE_ETAG}"`);

  assert.throws(
    () =>
      reconcileInventory({
        objects: [object('site-data/model-a/task-a/meta.json')],
        modelIds: ['model-a'],
        taskIds: ['task-a'],
        expectedFailures: new Set(),
      }),
    /must contain meta.json and output.glb/,
  );
  assert.throws(
    () =>
      reconcileInventory({
        objects: [object('site-data/model-a/task-a/meta.json'), object('site-data/model-a/task-a/debug.txt')],
        modelIds: ['model-a'],
        taskIds: ['task-a'],
        expectedFailures: new Set(),
      }),
    /unexpected site-data cell file/,
  );
});

test('R2 inventory follows continuation tokens without duplicating objects', async () => {
  const calls = [];
  const client = {
    async send(command) {
      calls.push(command.input);
      if (calls.length === 1) {
        return {
          Contents: [{ Key: 'site-data/model-a/task-a/meta.json', Size: 2, ETag: '"first"' }],
          IsTruncated: true,
          NextContinuationToken: 'page-two',
        };
      }
      return {
        Contents: [{ Key: 'site-data/model-a/task-a/output.glb', Size: 12, ETag: '"second"' }],
        IsTruncated: false,
      };
    },
  };
  const objects = await listSiteDataObjects(client, { bucket: '3dgen-runs', prefix: 'site-data' });
  assert.deepEqual(calls, [
    { Bucket: '3dgen-runs', Prefix: 'site-data/' },
    { Bucket: '3dgen-runs', Prefix: 'site-data/', ContinuationToken: 'page-two' },
  ]);
  assert.deepEqual(objects.map((item) => item.key), [
    'site-data/model-a/task-a/meta.json',
    'site-data/model-a/task-a/output.glb',
  ]);
});

test('cache metadata matches only the exact source, recipe, backend, and thumbnail hash', () => {
  const source = { etag: SOURCE_ETAG, size: 123 };
  const sourceSha256 = sha256('source');
  const fingerprint = renderFingerprint({ version: 1, backend: 'swiftshader' });
  const expected = expectedThumbnailMetadata({ source, sourceSha256, fingerprint, backend: 'swiftshader' });
  const metadata = { ...expected, 'thumb-sha256': sha256('thumbnail') };
  assert.deepEqual(evaluateCacheMetadata(metadata, expected), {
    matches: true,
    sourceSha256: metadata['source-sha256'],
    thumbSha256: metadata['thumb-sha256'],
    metadata,
  });
  const identity = expectedCacheIdentity({ source, fingerprint, backend: 'swiftshader' });
  assert.equal(evaluateCacheMetadata(metadata, identity).matches, true);
  assert.equal(evaluateCacheMetadata({ ...metadata, backend: 'gpu' }, expected).matches, false);
  assert.equal(evaluateCacheMetadata({ ...metadata, extra: 'value' }, expected).matches, false);
  assert.equal(evaluateCacheMetadata({ ...metadata, 'thumb-sha256': 'invalid' }, expected).matches, false);
});

test('thumbnail writes use create-only or exact-version replacement conditions', () => {
  assert.deepEqual(thumbnailWriteCondition(null), { IfNoneMatch: '*' });
  assert.deepEqual(thumbnailWriteCondition(THUMB_ETAG), { IfMatch: `"${THUMB_ETAG}"` });
});

test('check mode accepts a decoded fresh thumbnail without downloading the GLB', async () => {
  const sourceBytes = Buffer.from('glTF-test-source');
  const thumbnailBytes = await opaqueWebp();
  const recipe = { version: 1, webp: WEBP_OPTIONS, backend: 'swiftshader' };
  const fingerprint = renderFingerprint(recipe);
  const expectedBase = expectedThumbnailMetadata({
    source: { etag: SOURCE_ETAG, size: sourceBytes.length },
    sourceSha256: sha256(sourceBytes),
    fingerprint,
    backend: 'swiftshader',
  });
  const metadata = { ...expectedBase, 'thumb-sha256': sha256(thumbnailBytes) };
  const calls = [];
  const client = {
    async send(command) {
      calls.push({ name: commandName(command), input: command.input });
      if (commandName(command) === 'ListObjectsV2Command') {
        return {
          Contents: [
            { Key: 'site-data/model-a/task-a/meta.json', Size: 2, ETag: '"meta"' },
            { Key: 'site-data/model-a/task-a/output.glb', Size: sourceBytes.length, ETag: `"${SOURCE_ETAG}"` },
            { Key: 'site-data/model-a/task-a/thumb.webp', Size: thumbnailBytes.length, ETag: `"${THUMB_ETAG}"` },
          ],
          IsTruncated: false,
        };
      }
      if (commandName(command) === 'HeadObjectCommand') {
        return {
          ETag: `"${THUMB_ETAG}"`,
          ContentLength: thumbnailBytes.length,
          ContentType: 'image/webp',
          CacheControl: THUMBNAIL_CACHE_CONTROL,
          Metadata: metadata,
        };
      }
      if (commandName(command) === 'GetObjectCommand' && command.input.Key.endsWith('thumb.webp')) {
        assert.equal(command.input.IfMatch, `"${THUMB_ETAG}"`);
        return {
          ETag: `"${THUMB_ETAG}"`,
          ContentLength: thumbnailBytes.length,
          ContentType: 'image/webp',
          CacheControl: THUMBNAIL_CACHE_CONTROL,
          Metadata: metadata,
          Body: Readable.from([thumbnailBytes]),
        };
      }
      throw new Error(`unexpected fake S3 command: ${commandName(command)}`);
    },
  };
  const report = {};
  await runThumbnailBatch({
    client,
    bucket: '3dgen-runs',
    prefix: 'site-data',
    modelIds: ['model-a'],
    taskIds: ['task-a'],
    expectedFailures: new Set(),
    backend: 'swiftshader',
    check: true,
    force: false,
    rendererRecipe: recipe,
    webpOptions: WEBP_OPTIONS,
    createRenderer: async () => {
      throw new Error('fresh cache must not start a renderer');
    },
    report,
  });
  assert.equal(report.cells[0].status, 'fresh');
  assert.equal(report.cells[0].source.sha256, sha256(sourceBytes));
  assert.equal(
    calls.some((call) => call.name === 'GetObjectCommand' && call.input.Key.endsWith('output.glb')),
    false,
  );
  assert.equal(calls.some((call) => call.name === 'PutObjectCommand'), false);
});

test('normal mode rebuilds a missing thumbnail and verifies the exact uploaded object', async () => {
  const sourceBytes = Buffer.from('glTF-render-source');
  const recipe = { version: 2, webp: WEBP_OPTIONS, backend: 'swiftshader' };
  let stored = null;
  let rendererClosed = false;
  const client = {
    async send(command) {
      const name = commandName(command);
      if (name === 'ListObjectsV2Command') {
        return {
          Contents: [
            { Key: 'site-data/model-a/task-a/meta.json', Size: 2, ETag: '"meta"' },
            { Key: 'site-data/model-a/task-a/output.glb', Size: sourceBytes.length, ETag: `"${SOURCE_ETAG}"` },
          ],
          IsTruncated: false,
        };
      }
      if (name === 'GetObjectCommand' && command.input.Key.endsWith('output.glb')) {
        assert.equal(command.input.IfMatch, `"${SOURCE_ETAG}"`);
        return {
          ETag: `"${SOURCE_ETAG}"`,
          ContentLength: sourceBytes.length,
          Body: Readable.from([sourceBytes]),
        };
      }
      if (name === 'HeadObjectCommand' && command.input.Key.endsWith('output.glb')) {
        assert.equal(command.input.IfMatch, `"${SOURCE_ETAG}"`);
        return {
          ETag: `"${SOURCE_ETAG}"`,
          ContentLength: sourceBytes.length,
        };
      }
      if (name === 'HeadObjectCommand' && !stored) {
        const error = new Error('missing');
        error.name = 'NotFound';
        error.$metadata = { httpStatusCode: 404 };
        throw error;
      }
      if (name === 'PutObjectCommand') {
        stored = {
          bytes: Buffer.from(command.input.Body),
          metadata: command.input.Metadata,
          contentType: command.input.ContentType,
        };
        assert.equal(command.input.Key, 'site-data/model-a/task-a/thumb.webp');
        assert.equal(command.input.ContentLength, stored.bytes.length);
        assert.equal(command.input.CacheControl, THUMBNAIL_CACHE_CONTROL);
        assert.equal(command.input.IfNoneMatch, '*');
        assert.equal(command.input.IfMatch, undefined);
        return { ETag: `"${THUMB_ETAG}"` };
      }
      if (name === 'HeadObjectCommand' && stored) {
        return {
          ETag: `"${THUMB_ETAG}"`,
          ContentLength: stored.bytes.length,
          ContentType: stored.contentType,
          CacheControl: THUMBNAIL_CACHE_CONTROL,
          Metadata: stored.metadata,
        };
      }
      if (name === 'GetObjectCommand' && command.input.Key.endsWith('thumb.webp') && stored) {
        return {
          ETag: `"${THUMB_ETAG}"`,
          ContentLength: stored.bytes.length,
          ContentType: stored.contentType,
          CacheControl: THUMBNAIL_CACHE_CONTROL,
          Metadata: stored.metadata,
          Body: Readable.from([stored.bytes]),
        };
      }
      throw new Error(`unexpected fake S3 command: ${name}`);
    },
  };
  const report = {};
  await runThumbnailBatch({
    client,
    bucket: '3dgen-runs',
    prefix: 'site-data',
    modelIds: ['model-a'],
    taskIds: ['task-a'],
    expectedFailures: new Set(),
    backend: 'swiftshader',
    check: false,
    force: false,
    rendererRecipe: recipe,
    webpOptions: WEBP_OPTIONS,
    createRenderer: async () => ({
      recipe,
      async render({ outputPath }) {
        await sharp({
          create: {
            width: 320,
            height: 320,
            channels: 4,
            background: { r: 20, g: 120, b: 220, alpha: 1 },
          },
        })
          .png()
          .toFile(outputPath);
        return {
          width: 320,
          height: 320,
          webglRenderer: 'Fake WebGL',
          stats: { meshes: 1, triangles: 12, vertices: 8 },
        };
      },
      async close() {
        rendererClosed = true;
      },
    }),
    report,
  });
  assert.equal(report.cells[0].status, 'rendered');
  assert.equal(rendererClosed, true);
  assert.equal(stored.contentType, 'image/webp');
  assert.equal(stored.metadata['source-sha256'], createHash('sha256').update(sourceBytes).digest('hex'));
  assert.equal(stored.metadata['thumb-sha256'], sha256(stored.bytes));
  assert.deepEqual(Object.keys(stored.metadata).sort(), [
    'backend',
    'height',
    'render-fingerprint',
    'source-etag',
    'source-sha256',
    'source-size',
    'thumb-sha256',
    'width',
  ]);
});

test('source replacement during rendering fails before thumbnail PUT', async () => {
  const sourceBytes = Buffer.from('glTF-racing-source');
  const recipe = { version: 3, webp: WEBP_OPTIONS, backend: 'swiftshader' };
  let putAttempted = false;
  const client = {
    async send(command) {
      const name = commandName(command);
      if (name === 'ListObjectsV2Command') {
        return {
          Contents: [
            { Key: 'site-data/model-a/task-a/meta.json', Size: 2, ETag: '"meta"' },
            { Key: 'site-data/model-a/task-a/output.glb', Size: sourceBytes.length, ETag: `"${SOURCE_ETAG}"` },
          ],
          IsTruncated: false,
        };
      }
      if (name === 'HeadObjectCommand' && command.input.Key.endsWith('thumb.webp')) {
        const error = new Error('missing');
        error.name = 'NotFound';
        error.$metadata = { httpStatusCode: 404 };
        throw error;
      }
      if (name === 'GetObjectCommand' && command.input.Key.endsWith('output.glb')) {
        return {
          ETag: `"${SOURCE_ETAG}"`,
          ContentLength: sourceBytes.length,
          Body: Readable.from([sourceBytes]),
        };
      }
      if (name === 'HeadObjectCommand' && command.input.Key.endsWith('output.glb')) {
        const error = new Error('precondition failed');
        error.name = 'PreconditionFailed';
        error.$metadata = { httpStatusCode: 412 };
        throw error;
      }
      if (name === 'PutObjectCommand') {
        putAttempted = true;
        throw new Error('PUT must not be attempted');
      }
      throw new Error(`unexpected fake S3 command: ${name}`);
    },
  };

  await assert.rejects(
    runThumbnailBatch({
      client,
      bucket: '3dgen-runs',
      prefix: 'site-data',
      modelIds: ['model-a'],
      taskIds: ['task-a'],
      expectedFailures: new Set(),
      backend: 'swiftshader',
      check: false,
      force: false,
      rendererRecipe: recipe,
      webpOptions: WEBP_OPTIONS,
      createRenderer: async () => ({
        recipe,
        async render({ outputPath }) {
          await sharp({
            create: {
              width: 320,
              height: 320,
              channels: 4,
              background: { r: 30, g: 100, b: 180, alpha: 1 },
            },
          })
            .png()
            .toFile(outputPath);
          return {
            width: 320,
            height: 320,
            webglRenderer: 'Fake WebGL',
            stats: { meshes: 1, triangles: 1, vertices: 3 },
          };
        },
        async close() {},
      }),
      report: {},
    }),
    /source changed while thumbnail was being published/,
  );
  assert.equal(putAttempted, false);
});
