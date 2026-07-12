import assert from 'node:assert/strict';
import test from 'node:test';

import { buildSelectedEvidence } from './orientation-evidence-build.mjs';
import { finalizeSelectedEvidence, parseEvidenceJson } from './orientation-finalize.mjs';

const modelIds = ['model-a', 'model-b'];
const taskIds = ['task-a'];
const expectedFailures = new Set(['model-b/task-a']);
const digest = 'a'.repeat(64);
const rotation = { x: 0, y: 45, z: 0 };
const scores = { total: 0.8, iou: 0.7, edgeF1: 0.6, spatial: 0.5 };

function reportCell() {
  const candidates = Array.from({ length: 24 }, (_, index) => {
    const y = index * 15 < 180 ? index * 15 : index * 15 - 360;
    return {
      rank: index + 1,
      id: `x0:y${y}:z0`,
      rotation: { x: 0, y, z: 0 },
      scores,
    };
  });
  candidates[0] = { rank: 1, id: 'x0:y45:z0', rotation, scores };
  candidates[3] = { rank: 4, id: 'x0:y0:z0', rotation: { x: 0, y: 0, z: 0 }, scores };
  return {
    modelId: 'model-a',
    taskId: 'task-a',
    status: 'ranked',
    candidateCount: 24,
    margin: 0.2,
    source: { key: 'site-data/model-a/task-a/output.glb', etag: 'etag', size: 10, sha256: digest },
    referenceMask: { file: 'task-a.png', sha256: digest },
    rankedCandidates: candidates,
  };
}

function fixtures() {
  const report = {
    schemaVersion: 1,
    ok: true,
    recipe: { renderer: { version: 1, backend: 'gpu' } },
    cells: [reportCell()],
  };
  const fixes = {
    cells: {
      'model-a/task-a': { status: 'fixed', rotationDegrees: rotation, provenance: { kind: 'auto', score: 0.7, margin: 0.1, reviewed: true } },
      'model-b/task-a': { status: 'excluded', reason: 'expected-failure-no-glb' },
    },
  };
  return { report, fixes };
}

test('committed evidence deterministically finalizes the exact registry', () => {
  const { report, fixes } = fixtures();
  const evidence = buildSelectedEvidence({
    report,
    reportText: `${JSON.stringify(report)}\n`,
    fixes,
    modelIds,
    taskIds,
    expectedFailures,
  });
  const result = finalizeSelectedEvidence(evidence, { modelIds, taskIds, expectedFailures });
  assert.deepEqual(result.cells['model-a/task-a'].rotationDegrees, rotation);
  assert.deepEqual(result.cells['model-a/task-a'].provenance, { kind: 'auto', score: 0.8, margin: 0.2, reviewed: true });
  assert.equal(result.cells['model-b/task-a'].status, 'excluded');
});

test('evidence builder rejects duplicate, missing, unknown, and incomplete report cells', () => {
  const { report, fixes } = fixtures();
  const build = (value) => buildSelectedEvidence({
    report: value,
    reportText: JSON.stringify(value),
    fixes,
    modelIds,
    taskIds,
    expectedFailures,
  });
  assert.throws(() => build({ ...report, cells: [reportCell(), reportCell()] }), /exactly 1 success cells/);
  assert.throws(() => build({ ...report, cells: [] }), /exactly 1 success cells/);
  assert.throws(() => build({ ...report, cells: [{ ...reportCell(), modelId: 'unknown' }] }), /unknown cell/);
  assert.throws(() => build({ ...report, cells: [{ ...reportCell(), rankedCandidates: [] }] }), /complete ranked candidate/);
  assert.throws(
    () => build({ ...report, cells: [{ ...reportCell(), candidateCount: 1, rankedCandidates: reportCell().rankedCandidates.slice(0, 1) }] }),
    /complete ranked candidate/,
  );
});

test('finalizer rejects evidence drift and extra fields', () => {
  const { report, fixes } = fixtures();
  const evidence = buildSelectedEvidence({
    report,
    reportText: JSON.stringify(report),
    fixes,
    modelIds,
    taskIds,
    expectedFailures,
  });
  assert.throws(
    () => finalizeSelectedEvidence({ ...evidence, extra: true }, { modelIds, taskIds, expectedFailures }),
    /must contain exactly/,
  );
  const changed = structuredClone(evidence);
  changed.cells['model-a/task-a'].source.key = 'site-data/model-a/other/output.glb';
  assert.throws(() => finalizeSelectedEvidence(changed, { modelIds, taskIds, expectedFailures }), /source.key differs/);
  assert.throws(() => parseEvidenceJson('{"schemaVersion":1,"schemaVersion":1}'), /duplicate JSON object key/);
});
