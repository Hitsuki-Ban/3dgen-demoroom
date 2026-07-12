import { createHash } from 'node:crypto';
import { access, mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import sharp from 'sharp';

export const PANEL_WIDTH = 256;
export const PANEL_HEIGHT = 286;
export const SHEET_COLUMNS = 4;
export const SHEET_ROWS = 3;

const IMAGE_HEIGHT = 256;
const LABEL_HEIGHT = PANEL_HEIGHT - IMAGE_HEIGHT;
const BACKGROUND = { r: 15, g: 23, b: 42, alpha: 1 };
const REQUIRED_OPTIONS = ['--search-report', '--references', '--models', '--tasks', '--output'];
const CANONICAL_CONTRACT = Object.freeze({ modelCount: 11, taskCount: 25, successCount: 274, failureCount: 1 });
const ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function fail(message) {
  throw new Error(`orientation contact sheets: ${message}`);
}

function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${label} must be a JSON object`);
  return value;
}

function exactKeys(value, keys, label) {
  const actual = Object.keys(object(value, label)).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(`${label} must contain exactly ${expected.join(', ')}`);
  }
}

function finiteUnit(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) {
    fail(`${label} must be a finite number in [0, 1]`);
  }
  return value;
}

function canonicalId(value, label) {
  if (typeof value !== 'string' || !ID_PATTERN.test(value)) fail(`${label} must be a canonical lowercase ID`);
  return value;
}

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function safeRelative(value, label) {
  if (typeof value !== 'string' || value.length === 0 || path.isAbsolute(value)) fail(`${label} must be a relative file path`);
  const normalized = value.replaceAll('\\', '/');
  if (normalized.split('/').some((part) => part === '' || part === '.' || part === '..')) fail(`${label} is not a safe relative file path`);
  return normalized;
}

function inside(root, relative, label) {
  const absoluteRoot = path.resolve(root);
  const resolved = path.resolve(absoluteRoot, relative);
  if (resolved !== absoluteRoot && !resolved.startsWith(`${absoluteRoot}${path.sep}`)) fail(`${label} escapes its root`);
  return resolved;
}

export function parseContactSheetArgs(argv) {
  if (!Array.isArray(argv)) fail('argv must be an array');
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index];
    const value = argv[index + 1];
    if (!REQUIRED_OPTIONS.includes(option)) fail(`unknown option ${JSON.stringify(option)}`);
    if (Object.hasOwn(result, option)) fail(`duplicate option ${option}`);
    if (typeof value !== 'string' || value.length === 0 || value.startsWith('--')) fail(`${option} requires a value`);
    result[option] = value;
  }
  for (const option of REQUIRED_OPTIONS) if (!Object.hasOwn(result, option)) fail(`missing required option ${option}`);
  return Object.freeze({
    searchReport: path.resolve(result['--search-report']),
    references: path.resolve(result['--references']),
    models: path.resolve(result['--models']),
    tasks: path.resolve(result['--tasks']),
    output: path.resolve(result['--output']),
  });
}

function parseModels(value, contract) {
  if (!Array.isArray(value) || value.length !== contract.modelCount) fail(`models must contain exactly ${contract.modelCount} IDs`);
  const ids = value.map((id, index) => canonicalId(id, `models[${index}]`));
  if (new Set(ids).size !== ids.length) fail('models contains duplicate IDs');
  return ids;
}

function parseTasks(value, contract) {
  if (!Array.isArray(value) || value.length !== contract.taskCount) fail(`tasks must contain exactly ${contract.taskCount} records`);
  const ids = new Set();
  return value.map((entry, index) => {
    object(entry, `tasks[${index}]`);
    const id = canonicalId(entry.id, `tasks[${index}].id`);
    if (ids.has(id)) fail(`tasks contains duplicate ID ${JSON.stringify(id)}`);
    ids.add(id);
    const expectedImage = `references/${id}.png`;
    if (entry.image !== expectedImage) fail(`tasks[${index}].image must be ${JSON.stringify(expectedImage)}`);
    return Object.freeze({ id, image: expectedImage });
  });
}

function parseContract(contract) {
  exactKeys(contract, ['modelCount', 'taskCount', 'successCount', 'failureCount'], 'inventory contract');
  for (const key of Object.keys(contract)) {
    if (!Number.isSafeInteger(contract[key]) || contract[key] < 0) fail(`inventory contract ${key} must be a non-negative integer`);
  }
  if (contract.modelCount * contract.taskCount !== contract.successCount + contract.failureCount) {
    fail('inventory contract does not cover the model/task matrix');
  }
  return contract;
}

function parseRotation(value, label) {
  exactKeys(value, ['x', 'y', 'z'], label);
  const rotation = {};
  for (const axis of ['x', 'y', 'z']) {
    const angle = value[axis];
    if (typeof angle !== 'number' || !Number.isFinite(angle) || angle < -180 || angle >= 180) {
      fail(`${label}.${axis} must be finite and in [-180, 180)`);
    }
    rotation[axis] = angle;
  }
  return Object.freeze(rotation);
}

function parseTop(top, label) {
  if (!Array.isArray(top) || top.length === 0) fail(`${label} must be a non-empty array`);
  const first = object(top[0], `${label}[0]`);
  exactKeys(first, ['rank', 'id', 'rotation', 'scores', 'file'], `${label}[0]`);
  if (first.rank !== 1) fail(`${label}[0].rank must be 1`);
  canonicalId(first.id.replaceAll(':', '-').replaceAll('.', '-'), `${label}[0].id`);
  const scores = object(first.scores, `${label}[0].scores`);
  exactKeys(scores, ['total', 'iou', 'edgeF1', 'spatial'], `${label}[0].scores`);
  for (const key of ['total', 'iou', 'edgeF1', 'spatial']) finiteUnit(scores[key], `${label}[0].scores.${key}`);
  return Object.freeze({
    file: safeRelative(first.file, `${label}[0].file`),
    rotation: parseRotation(first.rotation, `${label}[0].rotation`),
    score: scores.total,
  });
}

function parseReport(report, models, tasks, contract) {
  object(report, 'search report');
  if (report.schemaVersion !== 1 || report.ok !== true) fail('search report must be successful schemaVersion 1');
  const inventory = object(report.inventory, 'search report.inventory');
  const inventoryExpected = {
    modelCount: contract.modelCount,
    taskCount: contract.taskCount,
    successCellCount: contract.successCount,
    expectedFailureCount: contract.failureCount,
    selectedSuccessCellCount: contract.successCount,
  };
  for (const [key, expected] of Object.entries(inventoryExpected)) {
    if (inventory[key] !== expected) fail(`search report.inventory.${key} must be ${expected}`);
  }
  if (!Array.isArray(report.expectedFailures) || report.expectedFailures.length !== contract.failureCount) {
    fail(`search report.expectedFailures must contain exactly ${contract.failureCount} cells`);
  }
  const modelSet = new Set(models);
  const taskSet = new Set(tasks.map(({ id }) => id));
  const failures = new Set();
  for (const [index, key] of report.expectedFailures.entries()) {
    if (typeof key !== 'string') fail(`search report.expectedFailures[${index}] must be a model/task string`);
    const parts = key.split('/');
    if (parts.length !== 2 || !modelSet.has(parts[0]) || !taskSet.has(parts[1])) fail(`unknown expected failure ${JSON.stringify(key)}`);
    if (failures.has(key)) fail(`duplicate expected failure ${JSON.stringify(key)}`);
    failures.add(key);
  }
  if (!Array.isArray(report.cells) || report.cells.length !== contract.successCount) {
    fail(`search report.cells must contain exactly ${contract.successCount} ranked cells`);
  }
  if (typeof report.output !== 'string' || !path.isAbsolute(report.output)) fail('search report.output must be an absolute path');
  const cells = new Map();
  for (const [index, cellValue] of report.cells.entries()) {
    const cell = object(cellValue, `search report.cells[${index}]`);
    const modelId = canonicalId(cell.modelId, `search report.cells[${index}].modelId`);
    const taskId = canonicalId(cell.taskId, `search report.cells[${index}].taskId`);
    if (!modelSet.has(modelId) || !taskSet.has(taskId)) fail(`search report cell ${modelId}/${taskId} is outside the registry`);
    const key = `${modelId}/${taskId}`;
    if (failures.has(key)) fail(`expected failure ${key} must not have a ranked cell`);
    if (cells.has(key)) fail(`duplicate search report cell ${key}`);
    if (cell.status !== 'ranked') fail(`search report cell ${key} must have status "ranked"`);
    const margin = finiteUnit(cell.margin, `search report cell ${key}.margin`);
    if (typeof cell.ambiguous !== 'boolean') fail(`search report cell ${key}.ambiguous must be boolean`);
    cells.set(key, Object.freeze({
      modelId,
      taskId,
      margin,
      ambiguous: cell.ambiguous,
      top: parseTop(cell.top, `search report cell ${key}.top`),
    }));
  }
  for (const modelId of models) {
    for (const { id: taskId } of tasks) {
      const key = `${modelId}/${taskId}`;
      if (!cells.has(key) && !failures.has(key)) fail(`search report is missing cell ${key}`);
    }
  }
  return Object.freeze({ output: report.output, cells, failures });
}

async function requireDecodedImage(file, label) {
  let fileStat;
  try {
    fileStat = await stat(file);
  } catch {
    fail(`${label} is missing: ${file}`);
  }
  if (!fileStat.isFile() || fileStat.size === 0) fail(`${label} is not a non-empty file: ${file}`);
  try {
    const metadata = await sharp(file, { failOn: 'error' }).metadata();
    if (!metadata.width || !metadata.height) fail(`${label} has invalid dimensions: ${file}`);
  } catch (error) {
    if (error.message.startsWith('orientation contact sheets:')) throw error;
    fail(`${label} cannot be decoded: ${file}: ${error.message}`);
  }
}

function escapeXml(value) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

async function panel(source, label) {
  const base = sharp({ create: { width: PANEL_WIDTH, height: PANEL_HEIGHT, channels: 4, background: BACKGROUND } });
  const composites = [];
  if (source !== null) {
    const image = await sharp(source, { failOn: 'error' })
      .resize(PANEL_WIDTH, IMAGE_HEIGHT, { fit: 'contain', background: BACKGROUND })
      .png()
      .toBuffer();
    composites.push({ input: image, left: 0, top: 0 });
  }
  const svg = Buffer.from(
    `<svg width="${PANEL_WIDTH}" height="${LABEL_HEIGHT}" xmlns="http://www.w3.org/2000/svg">` +
    `<rect width="100%" height="100%" fill="#0f172a"/>` +
    `<text x="10" y="20" fill="#ffffff" font-family="sans-serif" font-size="14">${escapeXml(label)}</text></svg>`,
  );
  composites.push({ input: svg, left: 0, top: IMAGE_HEIGHT });
  return base.composite(composites).png({ compressionLevel: 9 }).toBuffer();
}

async function publishDirectory(staging, output) {
  const backup = `${output}.backup-${process.pid}`;
  await rm(backup, { recursive: true, force: true });
  let hadOutput = false;
  try {
    await access(output);
    hadOutput = true;
    await rename(output, backup);
  } catch (error) {
    if (hadOutput) throw error;
  }
  try {
    await rename(staging, output);
  } catch (error) {
    if (hadOutput) await rename(backup, output);
    throw error;
  }
  await rm(backup, { recursive: true, force: true });
}

export async function generateOrientationContactSheets(paths, inventoryContract) {
  exactKeys(paths, ['searchReport', 'references', 'models', 'tasks', 'output'], 'contact sheet paths');
  const contract = parseContract(inventoryContract);
  const [report, modelPayload, taskPayload] = await Promise.all([
    readFile(paths.searchReport, 'utf8').then(JSON.parse),
    readFile(paths.models, 'utf8').then(JSON.parse),
    readFile(paths.tasks, 'utf8').then(JSON.parse),
  ]).catch((error) => fail(`input JSON read failed: ${error.message}`));
  const models = parseModels(modelPayload, contract);
  const tasks = parseTasks(taskPayload, contract);
  const parsed = parseReport(report, models, tasks, contract);

  const sources = new Map();
  for (const task of tasks) {
    const reference = inside(paths.references, path.basename(task.image), `reference ${task.id}`);
    await requireDecodedImage(reference, `reference ${task.id}`);
    sources.set(`reference/${task.id}`, reference);
    for (const modelId of models) {
      const key = `${modelId}/${task.id}`;
      const cell = parsed.cells.get(key);
      if (!cell) continue;
      const candidate = inside(parsed.output, cell.top.file, `candidate ${key}`);
      await requireDecodedImage(candidate, `candidate ${key}`);
      sources.set(key, candidate);
    }
  }

  const output = path.resolve(paths.output);
  const parent = path.dirname(output);
  await mkdir(parent, { recursive: true });
  const staging = await mkdtemp(path.join(parent, `.${path.basename(output)}.staging-`));
  try {
    const index = { schemaVersion: 1, columns: SHEET_COLUMNS, rows: SHEET_ROWS, panel: { width: PANEL_WIDTH, height: PANEL_HEIGHT }, tasks: [] };
    for (const task of tasks) {
      const panelRecords = [{ source: task.image, rotation: null, score: null, margin: null, ambiguous: false }];
      const panelBuffers = [await panel(sources.get(`reference/${task.id}`), 'reference')];
      for (const modelId of models) {
        const key = `${modelId}/${task.id}`;
        const cell = parsed.cells.get(key);
        if (cell) {
          panelBuffers.push(await panel(sources.get(key), modelId));
          panelRecords.push({ source: cell.top.file, rotation: cell.top.rotation, score: cell.top.score, margin: cell.margin, ambiguous: cell.ambiguous });
        } else {
          if (!parsed.failures.has(key)) fail(`internal inventory mismatch for ${key}`);
          panelBuffers.push(await panel(null, `${modelId} (expected failure)`));
          panelRecords.push({ source: null, rotation: null, score: null, margin: null, ambiguous: false });
        }
      }
      while (panelBuffers.length < SHEET_COLUMNS * SHEET_ROWS) panelBuffers.push(await panel(null, ''));
      if (panelBuffers.length !== SHEET_COLUMNS * SHEET_ROWS) fail(`task ${task.id} does not fit the fixed 4x3 sheet`);
      const composites = panelBuffers.map((input, index) => ({
        input,
        left: (index % SHEET_COLUMNS) * PANEL_WIDTH,
        top: Math.floor(index / SHEET_COLUMNS) * PANEL_HEIGHT,
      }));
      const bytes = await sharp({
        create: { width: SHEET_COLUMNS * PANEL_WIDTH, height: SHEET_ROWS * PANEL_HEIGHT, channels: 4, background: BACKGROUND },
      }).composite(composites).png({ compressionLevel: 9 }).toBuffer();
      const filename = `${task.id}.png`;
      await writeFile(path.join(staging, filename), bytes, { flag: 'wx' });
      index.tasks.push({ task: task.id, file: filename, sha256: sha256(bytes), panels: panelRecords });
    }
    await writeFile(path.join(staging, 'index.json'), `${JSON.stringify(index, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    await publishDirectory(staging, output);
    return index;
  } finally {
    await rm(staging, { recursive: true, force: true });
  }
}

export async function main(argv = process.argv.slice(2)) {
  try {
    await generateOrientationContactSheets(parseContactSheetArgs(argv), CANONICAL_CONTRACT);
    return 0;
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) process.exitCode = await main();
