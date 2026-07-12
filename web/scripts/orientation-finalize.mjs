import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { visit } from 'jsonc-parser';

import { parseModelRegistry, parseTasks } from './thumbnail-batch-lib.mjs';
import { parseOrientationFixes, validateOrientationFixes } from './orientation-fixes-lib.mjs';

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const repositoryRoot = path.resolve(webRoot, '..');

function object(value, name) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${name} must be an object`);
  return value;
}

function exactFields(value, expected, name) {
  const actual = Object.keys(object(value, name)).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((field, index) => field !== wanted[index])) {
    throw new TypeError(`${name} must contain exactly [${wanted.join(', ')}]`);
  }
}

function finiteUnit(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new TypeError(`${name} must be finite and in [0, 1]`);
  }
  return value;
}

function sha256(value, name) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) throw new TypeError(`${name} must be lowercase SHA-256`);
  return value;
}

function positiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value < 1) throw new TypeError(`${name} must be a positive safe integer`);
  return value;
}

export function parseEvidenceJson(text) {
  if (typeof text !== 'string') throw new TypeError('evidence JSON must be a string');
  const objectKeys = [];
  visit(text, {
    onObjectBegin: () => objectKeys.push(new Set()),
    onObjectProperty: (property) => {
      const keys = objectKeys.at(-1);
      if (keys.has(property)) throw new SyntaxError(`duplicate JSON object key ${JSON.stringify(property)}`);
      keys.add(property);
    },
    onObjectEnd: () => objectKeys.pop(),
    onError: (error, offset) => { throw new SyntaxError(`invalid evidence JSON error ${error} at offset ${offset}`); },
  }, { allowTrailingComma: false, disallowComments: true });
  return JSON.parse(text);
}

export function finalizeSelectedEvidence(evidence, { modelIds, taskIds, expectedFailures }) {
  exactFields(evidence, ['schemaVersion', 'searchReport', 'modelOrder', 'taskOrder', 'expectedFailures', 'cells'], '$');
  if (evidence.schemaVersion !== 1) throw new TypeError('$.schemaVersion must be 1');
  exactFields(evidence.searchReport, ['sha256', 'recipeSha256', 'rendererFingerprint'], '$.searchReport');
  for (const field of ['sha256', 'recipeSha256', 'rendererFingerprint']) sha256(evidence.searchReport[field], `$.searchReport.${field}`);
  if (JSON.stringify(evidence.modelOrder) !== JSON.stringify(modelIds)) throw new TypeError('$.modelOrder differs from registry');
  if (JSON.stringify(evidence.taskOrder) !== JSON.stringify(taskIds)) throw new TypeError('$.taskOrder differs from registry');
  if (JSON.stringify(evidence.expectedFailures) !== JSON.stringify([...expectedFailures].sort())) {
    throw new TypeError('$.expectedFailures differs from registry');
  }
  const expectedKeys = modelIds.flatMap((modelId) => taskIds.map((taskId) => `${modelId}/${taskId}`));
  exactFields(evidence.cells, expectedKeys, '$.cells');
  const cells = {};
  for (const key of expectedKeys) {
    const record = evidence.cells[key];
    if (expectedFailures.has(key)) {
      exactFields(record, ['status', 'reason'], `$.cells.${key}`);
      cells[key] = record;
      continue;
    }
    exactFields(record, ['status', 'selection', 'source', 'referenceMask', 'provenance'], `$.cells.${key}`);
    if (record.status !== 'fixed') throw new TypeError(`$.cells.${key}.status must be fixed`);
    exactFields(record.selection, ['rank', 'rotationDegrees', 'scores', 'margin'], `$.cells.${key}.selection`);
    positiveInteger(record.selection.rank, `$.cells.${key}.selection.rank`);
    exactFields(record.selection.scores, ['total', 'iou', 'edgeF1', 'spatial'], `$.cells.${key}.selection.scores`);
    for (const field of ['total', 'iou', 'edgeF1', 'spatial']) finiteUnit(record.selection.scores[field], `$.cells.${key}.selection.scores.${field}`);
    finiteUnit(record.selection.margin, `$.cells.${key}.selection.margin`);
    exactFields(record.source, ['key', 'etag', 'size', 'sha256'], `$.cells.${key}.source`);
    if (record.source.key !== `site-data/${key}/output.glb`) throw new TypeError(`$.cells.${key}.source.key differs`);
    if (typeof record.source.etag !== 'string' || record.source.etag.length === 0) throw new TypeError(`$.cells.${key}.source.etag is invalid`);
    positiveInteger(record.source.size, `$.cells.${key}.source.size`);
    sha256(record.source.sha256, `$.cells.${key}.source.sha256`);
    exactFields(record.referenceMask, ['file', 'sha256'], `$.cells.${key}.referenceMask`);
    if (record.referenceMask.file !== `${key.split('/')[1]}.png`) throw new TypeError(`$.cells.${key}.referenceMask.file differs`);
    sha256(record.referenceMask.sha256, `$.cells.${key}.referenceMask.sha256`);
    cells[key] = {
      status: 'fixed',
      rotationDegrees: record.selection.rotationDegrees,
      provenance: record.provenance,
    };
  }
  return validateOrientationFixes(
    { schemaVersion: 1, rotationSpace: 'absolute-object-local', eulerOrder: 'XYZ', cells },
    { modelIds, taskIds, expectedFailures },
  );
}

async function writeAtomic(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    await rm(file, { force: true });
    await rename(temporary, file);
  } finally {
    await rm(temporary, { force: true });
  }
}

export async function main() {
  const [models, tasks, evidenceText] = await Promise.all([
    readFile(path.join(webRoot, 'src/data/model-registry.json'), 'utf8').then(JSON.parse),
    readFile(path.join(repositoryRoot, 'tasks/tasks.json'), 'utf8').then(JSON.parse),
    readFile(path.join(webRoot, 'src/data/orientation-selected-evidence.json'), 'utf8'),
  ]);
  const modelIds = parseModelRegistry(models);
  const taskIds = parseTasks(tasks);
  const expectedFailures = new Set(['partcrafter/chrome-espresso-machine']);
  const result = finalizeSelectedEvidence(parseEvidenceJson(evidenceText), { modelIds, taskIds, expectedFailures });
  const output = path.join(webRoot, 'src/data/orientation-fixes.json');
  await writeAtomic(output, result);
  const reparsed = parseOrientationFixes(await readFile(output, 'utf8'), { modelIds, taskIds, expectedFailures });
  process.stdout.write(`wrote ${Object.keys(reparsed.cells).length} audited orientation records to ${output}\n`);
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) await main();
