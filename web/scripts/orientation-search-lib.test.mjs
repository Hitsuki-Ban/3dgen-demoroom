import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import sharp from 'sharp';

import {
  canonicalDegrees,
  formatTopCandidates,
  generateOrientationCandidates,
  parseOrientationSearchArgs,
  runOrientationSearch,
} from './orientation-search-lib.mjs';

const REQUIRED_ARGS = [
  '--r2-root', 's3://bucket-name/site-data',
  '--output', 'out',
  '--reference-mask-root', 'masks',
  '--report', 'report.json',
  '--backend', 'swiftshader',
  '--expected-failure', 'failed-model/task-a',
];

test('standard candidates cover one canonical yaw circle without duplicates', () => {
  const candidates = generateOrientationCandidates('sf3d');
  assert.equal(candidates.length, 24);
  assert.equal(new Set(candidates.map((candidate) => candidate.id)).size, candidates.length);
  assert.deepEqual(candidates[0].rotation, { x: 0, y: 0, z: 0 });
  assert.ok(candidates.some((candidate) => candidate.rotation.y === -180));
  for (const candidate of candidates) {
    for (const value of Object.values(candidate.rotation)) assert.ok(value >= -180 && value < 180);
  }
  assert.equal(canonicalDegrees(180), -180);
  assert.equal(canonicalDegrees(360), 0);
});

test('tilted candidates cover pitch/roll grid and deduplicate equivalent Euler rotations', () => {
  const candidates = generateOrientationCandidates('triposr');
  assert.equal(candidates.length, 251);
  assert.equal(new Set(candidates.map((candidate) => candidate.id)).size, candidates.length);
  assert.ok(candidates.some((candidate) => candidate.rotation.x === -90));
  assert.ok(candidates.some((candidate) => candidate.rotation.x === 90));
  assert.ok(candidates.some((candidate) => candidate.rotation.z === -90));
  assert.ok(candidates.some((candidate) => candidate.rotation.z === 90));
  assert.equal(generateOrientationCandidates('3dtopia-xl').length, 251);
  for (const candidate of candidates) {
    for (const value of Object.values(candidate.rotation)) assert.ok(value >= -180 && value < 180);
  }
});

test('top candidate formatting preserves stable ranking order and score components', () => {
  const rotations = [
    { id: 'first', rotation: { x: 0, y: 0, z: 0 } },
    { id: 'second', rotation: { x: 0, y: 15, z: 0 } },
  ];
  const ranking = {
    ranked: [
      { id: 'first', total: 0.8, iou: 0.7, edgeF1: 0.6, spatial: 0.5 },
      { id: 'second', total: 0.8, iou: 0.6, edgeF1: 0.5, spatial: 0.4 },
    ],
  };
  const formatted = formatTopCandidates(ranking, new Map(rotations.map((item) => [item.id, item])));
  assert.deepEqual(formatted.map((item) => item.id), ['first', 'second']);
  assert.deepEqual(formatted[0].scores, { total: 0.8, iou: 0.7, edgeF1: 0.6, spatial: 0.5 });
});

test('CLI requires every explicit input and rejects duplicates, defaults, positionals, and invalid filters', () => {
  const parsed = parseOrientationSearchArgs([...REQUIRED_ARGS, '--model', 'sf3d', '--task', 'task-a']);
  assert.equal(parsed.backend, 'swiftshader');
  assert.equal(parsed.r2Root.bucket, 'bucket-name');
  assert.deepEqual([...parsed.expectedFailures], ['failed-model/task-a']);
  for (const required of ['--r2-root', '--output', '--reference-mask-root', '--report', '--backend']) {
    const index = REQUIRED_ARGS.indexOf(required);
    assert.throws(() => parseOrientationSearchArgs(REQUIRED_ARGS.toSpliced(index, 2)), new RegExp(`${required} is required`));
  }
  assert.throws(() => parseOrientationSearchArgs(REQUIRED_ARGS.slice(0, -2)), /at least one explicit --expected-failure/);
  assert.throws(() => parseOrientationSearchArgs([...REQUIRED_ARGS, '--backend', 'gpu']), /may only be provided once/);
  assert.throws(() => parseOrientationSearchArgs([...REQUIRED_ARGS, 'extra']), /unknown orientation search argument/);
  assert.throws(() => parseOrientationSearchArgs([...REQUIRED_ARGS, '--model', 'Bad']), /must match/);
  assert.throws(() => parseOrientationSearchArgs(REQUIRED_ARGS.with(9, 'auto')), /must be swiftshader or gpu/);
  assert.equal(parseOrientationSearchArgs([...REQUIRED_ARGS, '--review-all-candidates']).reviewAllCandidates, true);
  assert.throws(
    () => parseOrientationSearchArgs([...REQUIRED_ARGS, '--review-all-candidates', '--review-all-candidates']),
    /may only be provided once/,
  );
});

function inventoryObjects() {
  return [
    { key: 'site-data/sf3d/task-a/meta.json', size: 2, etag: 'meta-etag' },
    { key: 'site-data/sf3d/task-a/output.glb', size: 4, etag: 'source-etag' },
    { key: 'site-data/failed-model/task-a/failure.json', size: 2, etag: 'failure-etag' },
  ];
}

async function makeMask(root) {
  const width = 32;
  const height = 32;
  const data = Buffer.alloc(width * height);
  for (let y = 8; y < 24; y += 1) for (let x = 8; x < 24; x += 1) data[y * width + x] = 255;
  await mkdir(root, { recursive: true });
  await sharp(data, { raw: { width, height, channels: 1 } })
    .toColourspace('b-w')
    .png({ palette: false })
    .toFile(path.join(root, 'task-a.png'));
}

async function candidatePng() {
  const width = 320;
  const height = 320;
  const data = Buffer.alloc(width * height * 4);
  for (let y = 80; y < 240; y += 1) {
    for (let x = 80; x < 240; x += 1) {
      const index = (y * width + x) * 4;
      data[index] = 200;
      data[index + 1] = 100;
      data[index + 2] = 50;
      data[index + 3] = 255;
    }
  }
  return sharp(data, { raw: { width, height, channels: 4 } }).png().toBuffer();
}

function fakeR2() {
  const requests = [];
  return {
    requests,
    async send(command) {
      requests.push(command.input);
      assert.equal(command.constructor.name, 'GetObjectCommand');
      assert.deepEqual(command.input, {
        Bucket: 'bucket-name',
        Key: 'site-data/sf3d/task-a/output.glb',
        IfMatch: '"source-etag"',
      });
      return { ETag: '"source-etag"', ContentLength: 4, Body: new Uint8Array([1, 2, 3, 4]) };
    },
  };
}

async function runFakeSearch({ failCapture = false, reviewAllCandidates = false } = {}) {
  const root = await mkdtemp(path.join(tmpdir(), 'orientation-search-test-'));
  const maskRoot = path.join(root, 'masks');
  const outputRoot = path.join(root, 'output');
  await makeMask(maskRoot);
  const png = await candidatePng();
  const counts = { renderer: 0, open: 0, capture: 0, sessionClose: 0, rendererClose: 0 };
  const client = fakeR2();
  const report = {};
  const createRenderer = async () => {
    counts.renderer += 1;
    return {
      recipe: { fake: true, backend: 'swiftshader' },
      async openSession() {
        counts.open += 1;
        return {
          webglRenderer: 'fake renderer',
          stats: { meshes: 1, triangles: 2, vertices: 3 },
          async capture({ outputPath }) {
            counts.capture += 1;
            if (failCapture) throw new Error('capture exploded');
            await writeFile(outputPath, png);
            return { width: 320, height: 320 };
          },
          async close() { counts.sessionClose += 1; },
        };
      },
      async close() { counts.rendererClose += 1; },
    };
  };
  const promise = runOrientationSearch({
    client,
    bucket: 'bucket-name',
    prefix: 'site-data',
    modelIds: ['sf3d', 'failed-model'],
    taskIds: ['task-a'],
    expectedFailures: new Set(['failed-model/task-a']),
    backend: 'swiftshader',
    outputRoot,
    referenceMaskRoot: maskRoot,
    createRenderer,
    reviewAllCandidates,
    report,
    temporaryParent: root,
    listObjects: async () => inventoryObjects(),
  });
  return { root, outputRoot, report, counts, client, promise };
}

test('R2 and renderer orchestration conditionally downloads once, opens once, and captures all candidates plus top five', async () => {
  const fixture = await runFakeSearch();
  try {
    await fixture.promise;
    assert.deepEqual(fixture.counts, { renderer: 1, open: 1, capture: 29, sessionClose: 1, rendererClose: 1 });
    assert.equal(fixture.client.requests.length, 1);
    assert.equal(fixture.report.inventory.successCellCount, 1);
    assert.equal(fixture.report.inventory.expectedFailureCount, 1);
    assert.equal(fixture.report.cells[0].candidateCount, 24);
    assert.equal(fixture.report.cells[0].rankedCandidates.length, 24);
    assert.equal(fixture.report.cells[0].top.length, 5);
    assert.equal(fixture.report.cells[0].source.sha256, '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a');
    for (const candidate of fixture.report.cells[0].top) {
      const bytes = await readFile(path.join(fixture.outputRoot, candidate.file));
      assert.ok(bytes.length > 0);
    }
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test('explicit review mode saves every candidate from the same model session', async () => {
  const fixture = await runFakeSearch({ reviewAllCandidates: true });
  try {
    await fixture.promise;
    assert.equal(fixture.report.cells[0].top.length, 24);
    assert.equal(fixture.report.recipe.search.savedCandidateCount, 'all');
    assert.deepEqual(fixture.counts, {
      renderer: 1,
      open: 1,
      capture: 48,
      sessionClose: 1,
      rendererClose: 1,
    });
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});

test('cell capture failure is recorded, closes resources, and rejects the whole search', async () => {
  const fixture = await runFakeSearch({ failCapture: true });
  try {
    await assert.rejects(fixture.promise, /1 orientation cell\(s\) failed/);
    assert.equal(fixture.report.cells[0].status, 'failed');
    assert.match(fixture.report.cells[0].error.message, /capture exploded/);
    assert.equal(fixture.report.errors.length, 1);
    assert.deepEqual(fixture.counts, { renderer: 1, open: 1, capture: 1, sessionClose: 1, rendererClose: 1 });
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
});
