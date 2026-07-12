const SAFE_ID = /^[a-z0-9-]+$/;
const TOP_LEVEL_FIELDS = ['schemaVersion', 'rotationSpace', 'eulerOrder', 'cells'];
const FIXED_FIELDS = ['status', 'rotationDegrees', 'provenance'];
const ROTATION_FIELDS = ['x', 'y', 'z'];
const AUTO_FIELDS = ['kind', 'score', 'margin', 'reviewed'];
const MANUAL_FIELDS = ['kind', 'reason', 'reviewed'];
const EXCLUDED_FIELDS = ['status', 'reason'];

function fail(path, message) {
  throw new TypeError(`${path} ${message}`);
}

function isObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requireObject(value, path) {
  if (!isObject(value)) fail(path, 'must be a JSON object');
}

function assertExactFields(value, expected, path) {
  requireObject(value, path);
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((field, index) => field !== wanted[index])) {
    fail(path, `must contain exactly fields [${wanted.join(', ')}], received [${actual.join(', ')}]`);
  }
}

function validateIds(values, name) {
  if (!Array.isArray(values) || values.length === 0) {
    fail(name, 'must be a non-empty array');
  }
  const seen = new Set();
  for (const value of values) {
    if (typeof value !== 'string' || !SAFE_ID.test(value)) {
      fail(name, 'entries must match [a-z0-9-]+');
    }
    if (seen.has(value)) fail(name, `contains duplicate ID ${JSON.stringify(value)}`);
    seen.add(value);
  }
  return [...values];
}

function validateRegistry({ modelIds, taskIds, expectedFailures } = {}) {
  const models = validateIds(modelIds, 'modelIds');
  const tasks = validateIds(taskIds, 'taskIds');
  if (!(expectedFailures instanceof Set)) fail('expectedFailures', 'must be a Set');

  const matrix = new Set(models.flatMap((modelId) => tasks.map((taskId) => `${modelId}/${taskId}`)));
  const failures = new Set();
  for (const key of expectedFailures) {
    if (typeof key !== 'string') fail('expectedFailures', 'entries must be model/task strings');
    if (!matrix.has(key)) fail('expectedFailures', `contains unknown cell ${JSON.stringify(key)}`);
    failures.add(key);
  }
  return { models, tasks, matrix, failures };
}

function validateAngle(value, path) {
  if (typeof value !== 'number' || !Number.isFinite(value)) fail(path, 'must be a finite number');
  if (value < -180 || value >= 180) fail(path, 'must be in canonical range [-180, 180)');
  return value;
}

function validateUnitInterval(value, path) {
  if (typeof value !== 'number' || !Number.isFinite(value)) fail(path, 'must be a finite number');
  if (value < 0 || value > 1) fail(path, 'must be in range [0, 1]');
  return value;
}

function validateProvenance(value, path) {
  requireObject(value, path);
  if (value.kind === 'auto') {
    assertExactFields(value, AUTO_FIELDS, path);
    if (value.reviewed !== true) fail(`${path}.reviewed`, 'must be true');
    return Object.freeze({
      kind: 'auto',
      score: validateUnitInterval(value.score, `${path}.score`),
      margin: validateUnitInterval(value.margin, `${path}.margin`),
      reviewed: true,
    });
  }
  if (value.kind === 'manual') {
    assertExactFields(value, MANUAL_FIELDS, path);
    if (typeof value.reason !== 'string' || value.reason.trim().length === 0) {
      fail(`${path}.reason`, 'must be a nonempty string');
    }
    if (value.reviewed !== true) fail(`${path}.reviewed`, 'must be true');
    return Object.freeze({ kind: 'manual', reason: value.reason, reviewed: true });
  }
  fail(`${path}.kind`, 'must be "auto" or "manual"');
}

function validateFixed(value, path) {
  assertExactFields(value, FIXED_FIELDS, path);
  if (value.status !== 'fixed') fail(`${path}.status`, 'must be "fixed"');
  assertExactFields(value.rotationDegrees, ROTATION_FIELDS, `${path}.rotationDegrees`);
  const rotationDegrees = Object.freeze({
    x: validateAngle(value.rotationDegrees.x, `${path}.rotationDegrees.x`),
    y: validateAngle(value.rotationDegrees.y, `${path}.rotationDegrees.y`),
    z: validateAngle(value.rotationDegrees.z, `${path}.rotationDegrees.z`),
  });
  return Object.freeze({
    status: 'fixed',
    rotationDegrees,
    provenance: validateProvenance(value.provenance, `${path}.provenance`),
  });
}

function validateExcluded(value, path) {
  assertExactFields(value, EXCLUDED_FIELDS, path);
  if (value.status !== 'excluded') fail(`${path}.status`, 'must be "excluded"');
  if (value.reason !== 'expected-failure-no-glb') {
    fail(`${path}.reason`, 'must be "expected-failure-no-glb"');
  }
  return Object.freeze({ status: 'excluded', reason: 'expected-failure-no-glb' });
}

export function validateOrientationFixes(value, registry) {
  const { models, tasks, matrix, failures } = validateRegistry(registry);
  assertExactFields(value, TOP_LEVEL_FIELDS, '$');
  if (value.schemaVersion !== 1) fail('$.schemaVersion', 'must be 1');
  if (value.rotationSpace !== 'absolute-object-local') {
    fail('$.rotationSpace', 'must be "absolute-object-local"');
  }
  if (value.eulerOrder !== 'XYZ') fail('$.eulerOrder', 'must be "XYZ"');
  requireObject(value.cells, '$.cells');

  const actualKeys = Object.keys(value.cells);
  for (const key of actualKeys) {
    if (!matrix.has(key)) fail('$.cells', `contains unknown cell ${JSON.stringify(key)}`);
  }
  for (const key of matrix) {
    if (!Object.hasOwn(value.cells, key)) fail('$.cells', `is missing required cell ${JSON.stringify(key)}`);
  }

  const cells = {};
  for (const modelId of models) {
    for (const taskId of tasks) {
      const key = `${modelId}/${taskId}`;
      const path = `$.cells[${JSON.stringify(key)}]`;
      const record = value.cells[key];
      requireObject(record, path);
      if (failures.has(key)) {
        if (record.status !== 'excluded') fail(`${path}.status`, 'must be "excluded" for an expected failure');
        cells[key] = validateExcluded(record, path);
      } else {
        if (record.status !== 'fixed') fail(`${path}.status`, 'must be "fixed" for a successful cell');
        cells[key] = validateFixed(record, path);
      }
    }
  }

  return Object.freeze({
    schemaVersion: 1,
    rotationSpace: 'absolute-object-local',
    eulerOrder: 'XYZ',
    cells: Object.freeze(cells),
  });
}

function assertNoDuplicateJsonKeys(text) {
  let index = 0;

  function syntax(message) {
    throw new SyntaxError(`invalid JSON at offset ${index}: ${message}`);
  }

  function skipWhitespace() {
    while (index < text.length && /[\t\n\r ]/.test(text[index])) index += 1;
  }

  function parseString() {
    if (text[index] !== '"') syntax('expected string');
    const start = index;
    index += 1;
    while (index < text.length) {
      const character = text[index];
      if (character === '"') {
        index += 1;
        return JSON.parse(text.slice(start, index));
      }
      if (character === '\\') {
        index += 2;
      } else {
        index += 1;
      }
    }
    syntax('unterminated string');
  }

  function parseValue() {
    skipWhitespace();
    const character = text[index];
    if (character === '{') return parseObject();
    if (character === '[') return parseArray();
    if (character === '"') {
      parseString();
      return;
    }
    const rest = text.slice(index);
    const token = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(rest)?.[0];
    if (!token) syntax('expected value');
    index += token.length;
  }

  function parseObject() {
    index += 1;
    skipWhitespace();
    const keys = new Set();
    if (text[index] === '}') {
      index += 1;
      return;
    }
    while (index < text.length) {
      skipWhitespace();
      const key = parseString();
      if (keys.has(key)) throw new SyntaxError(`duplicate JSON object key ${JSON.stringify(key)}`);
      keys.add(key);
      skipWhitespace();
      if (text[index] !== ':') syntax('expected colon');
      index += 1;
      parseValue();
      skipWhitespace();
      if (text[index] === '}') {
        index += 1;
        return;
      }
      if (text[index] !== ',') syntax('expected comma or closing brace');
      index += 1;
    }
    syntax('unterminated object');
  }

  function parseArray() {
    index += 1;
    skipWhitespace();
    if (text[index] === ']') {
      index += 1;
      return;
    }
    while (index < text.length) {
      parseValue();
      skipWhitespace();
      if (text[index] === ']') {
        index += 1;
        return;
      }
      if (text[index] !== ',') syntax('expected comma or closing bracket');
      index += 1;
    }
    syntax('unterminated array');
  }

  skipWhitespace();
  parseValue();
  skipWhitespace();
  if (index !== text.length) syntax('unexpected trailing content');
}

export function parseOrientationFixes(text, registry) {
  if (typeof text !== 'string') fail('orientation fixes input', 'must be a JSON string');
  assertNoDuplicateJsonKeys(text);
  return validateOrientationFixes(JSON.parse(text), registry);
}
