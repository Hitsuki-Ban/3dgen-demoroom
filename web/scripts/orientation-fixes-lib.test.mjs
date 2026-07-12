import assert from 'node:assert/strict';
import test from 'node:test';

import { parseOrientationFixes, validateOrientationFixes } from './orientation-fixes-lib.mjs';

const registry = Object.freeze({
  modelIds: ['model-a', 'model-b'],
  taskIds: ['task-a', 'task-b'],
  expectedFailures: new Set(['model-b/task-b']),
});

function auto(rotationDegrees = { x: 0, y: -180, z: 179.5 }) {
  return {
    status: 'fixed',
    rotationDegrees,
    provenance: { kind: 'auto', score: 0, margin: 1, reviewed: true },
  };
}

function manual() {
  return {
    status: 'fixed',
    rotationDegrees: { x: 10, y: 20, z: 30 },
    provenance: { kind: 'manual', reason: 'visual review selected the reference-facing view', reviewed: true },
  };
}

function excluded() {
  return { status: 'excluded', reason: 'expected-failure-no-glb' };
}

function validDocument() {
  return {
    schemaVersion: 1,
    rotationSpace: 'absolute-object-local',
    eulerOrder: 'XYZ',
    cells: {
      'model-a/task-a': auto(),
      'model-a/task-b': manual(),
      'model-b/task-a': auto({ x: -180, y: 0, z: 0 }),
      'model-b/task-b': excluded(),
    },
  };
}

function clone(value) {
  return structuredClone(value);
}

test('validates the exact matrix and returns an isolated deeply frozen view', () => {
  const input = validDocument();
  const result = validateOrientationFixes(input, registry);
  assert.deepEqual(result, input);
  assert.notEqual(result, input);
  assert.notEqual(result.cells, input.cells);
  assert.notEqual(result.cells['model-a/task-a'], input.cells['model-a/task-a']);
  assert.equal(Object.isFrozen(result), true);
  assert.equal(Object.isFrozen(result.cells), true);
  assert.equal(Object.isFrozen(result.cells['model-a/task-a']), true);
  assert.equal(Object.isFrozen(result.cells['model-a/task-a'].rotationDegrees), true);
  assert.equal(Object.isFrozen(result.cells['model-a/task-a'].provenance), true);

  input.cells['model-a/task-a'].rotationDegrees.x = 90;
  assert.equal(result.cells['model-a/task-a'].rotationDegrees.x, 0);
  assert.throws(() => {
    result.cells['model-a/task-a'].rotationDegrees.x = 45;
  }, TypeError);
});

test('parses strict JSON and rejects duplicate object keys at any depth', () => {
  const result = parseOrientationFixes(JSON.stringify(validDocument()), registry);
  assert.equal(result.cells['model-b/task-b'].status, 'excluded');
  assert.throws(() => parseOrientationFixes(42, registry), /must be a JSON string/);
  assert.throws(() => parseOrientationFixes('{', registry), /invalid JSON/);
  assert.throws(
    () => parseOrientationFixes('{"schemaVersion":1,"schemaVersion":1}', registry),
    /duplicate JSON object key "schemaVersion"/,
  );
  const duplicateNested = JSON.stringify(validDocument()).replace(
    '"score":0',
    '"score":0,"score":0.5',
  );
  assert.throws(() => parseOrientationFixes(duplicateNested, registry), /duplicate JSON object key "score"/);
});

test('requires exact top-level fields and constants', () => {
  for (const value of [null, [], 'document']) {
    assert.throws(() => validateOrientationFixes(value, registry), /must be a JSON object/);
  }
  for (const field of ['schemaVersion', 'rotationSpace', 'eulerOrder', 'cells']) {
    const document = validDocument();
    delete document[field];
    assert.throws(() => validateOrientationFixes(document, registry), /must contain exactly fields/);
  }
  const extra = validDocument();
  extra.extra = true;
  assert.throws(() => validateOrientationFixes(extra, registry), /must contain exactly fields/);
  for (const [field, value, pattern] of [
    ['schemaVersion', 2, /must be 1/],
    ['rotationSpace', 'world', /absolute-object-local/],
    ['eulerOrder', 'ZYX', /must be "XYZ"/],
  ]) {
    const document = validDocument();
    document[field] = value;
    assert.throws(() => validateOrientationFixes(document, registry), pattern);
  }
});

test('validates registry inputs and expected failures before the document', () => {
  assert.throws(() => validateOrientationFixes(validDocument(), undefined), /modelIds/);
  assert.throws(
    () => validateOrientationFixes(validDocument(), { ...registry, modelIds: [] }),
    /non-empty array/,
  );
  assert.throws(
    () => validateOrientationFixes(validDocument(), { ...registry, modelIds: ['model-a', 'model-a'] }),
    /duplicate ID/,
  );
  assert.throws(
    () => validateOrientationFixes(validDocument(), { ...registry, taskIds: ['Task'] }),
    /must match/,
  );
  assert.throws(
    () => validateOrientationFixes(validDocument(), { ...registry, expectedFailures: [] }),
    /must be a Set/,
  );
  assert.throws(
    () =>
      validateOrientationFixes(validDocument(), {
        ...registry,
        expectedFailures: new Set(['model-a/unknown']),
      }),
    /unknown cell/,
  );
  assert.throws(
    () => validateOrientationFixes(validDocument(), { ...registry, expectedFailures: new Set([123]) }),
    /model\/task strings/,
  );
});

test('requires exact registry × tasks coverage with no unknown cell keys', () => {
  const missing = validDocument();
  delete missing.cells['model-a/task-b'];
  assert.throws(() => validateOrientationFixes(missing, registry), /missing required cell "model-a\/task-b"/);

  const unknown = validDocument();
  unknown.cells['model-a/other'] = auto();
  assert.throws(() => validateOrientationFixes(unknown, registry), /unknown cell "model-a\/other"/);
  const nonObject = validDocument();
  nonObject.cells = [];
  assert.throws(() => validateOrientationFixes(nonObject, registry), /\$\.cells must be a JSON object/);
});

test('successful cells must be fixed and expected failures must be excluded', () => {
  const excludedSuccess = validDocument();
  excludedSuccess.cells['model-a/task-a'] = excluded();
  assert.throws(() => validateOrientationFixes(excludedSuccess, registry), /must be "fixed" for a successful cell/);

  const fixedFailure = validDocument();
  fixedFailure.cells['model-b/task-b'] = auto();
  assert.throws(() => validateOrientationFixes(fixedFailure, registry), /must be "excluded" for an expected failure/);
});

test('fixed records and rotations reject missing, extra, malformed, and noncanonical values', () => {
  const cases = [
    [(record) => delete record.provenance, /must contain exactly fields/],
    [(record) => (record.extra = true), /must contain exactly fields/],
    [(record) => (record.rotationDegrees = []), /must be a JSON object/],
    [(record) => delete record.rotationDegrees.z, /must contain exactly fields/],
    [(record) => (record.rotationDegrees.w = 0), /must contain exactly fields/],
    [(record) => (record.rotationDegrees.x = '0'), /finite number/],
    [(record) => (record.rotationDegrees.x = Number.NaN), /finite number/],
    [(record) => (record.rotationDegrees.y = Number.POSITIVE_INFINITY), /finite number/],
    [(record) => (record.rotationDegrees.x = -180.0001), /canonical range/],
    [(record) => (record.rotationDegrees.y = 180), /canonical range/],
  ];
  for (const [mutate, pattern] of cases) {
    const document = validDocument();
    mutate(document.cells['model-a/task-a']);
    assert.throws(() => validateOrientationFixes(document, registry), pattern);
  }
  assert.doesNotThrow(() => validateOrientationFixes(validDocument(), registry));
});

test('auto provenance is exact, reviewed, finite, and bounded to [0, 1]', () => {
  const cases = [
    [(value) => delete value.margin, /must contain exactly fields/],
    [(value) => (value.extra = true), /must contain exactly fields/],
    [(value) => (value.reviewed = false), /must be true/],
    [(value) => (value.score = -0.01), /range \[0, 1\]/],
    [(value) => (value.score = 1.01), /range \[0, 1\]/],
    [(value) => (value.margin = Number.NaN), /finite number/],
    [(value) => (value.margin = '1'), /finite number/],
  ];
  for (const [mutate, pattern] of cases) {
    const document = validDocument();
    mutate(document.cells['model-a/task-a'].provenance);
    assert.throws(() => validateOrientationFixes(document, registry), pattern);
  }
});

test('manual provenance requires its exact fields, a nonempty reason, and reviewed true', () => {
  const cases = [
    [(value) => delete value.reason, /must contain exactly fields/],
    [(value) => (value.score = 1), /must contain exactly fields/],
    [(value) => (value.reason = ''), /nonempty string/],
    [(value) => (value.reason = '   '), /nonempty string/],
    [(value) => (value.reason = 42), /nonempty string/],
    [(value) => (value.reviewed = false), /must be true/],
    [(value) => (value.kind = 'automatic'), /auto.*manual/],
  ];
  for (const [mutate, pattern] of cases) {
    const document = validDocument();
    mutate(document.cells['model-a/task-b'].provenance);
    assert.throws(() => validateOrientationFixes(document, registry), pattern);
  }
});

test('excluded records accept only the exact expected-failure contract', () => {
  for (const mutate of [
    (record) => delete record.reason,
    (record) => (record.extra = true),
    (record) => (record.reason = 'missing'),
  ]) {
    const document = validDocument();
    mutate(document.cells['model-b/task-b']);
    assert.throws(() => validateOrientationFixes(document, registry));
  }
});

test('rejects provenance type drift before inspecting its discriminator', () => {
  for (const provenance of [null, [], 'auto']) {
    const document = clone(validDocument());
    document.cells['model-a/task-a'].provenance = provenance;
    assert.throws(() => validateOrientationFixes(document, registry), /must be a JSON object/);
  }
});
