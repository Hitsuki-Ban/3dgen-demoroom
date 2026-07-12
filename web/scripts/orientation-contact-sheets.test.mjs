import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';

import sharp from 'sharp';

import {
  generateOrientationContactSheets,
  PANEL_HEIGHT,
  PANEL_WIDTH,
  parseContactSheetArgs,
  SHEET_COLUMNS,
  SHEET_ROWS,
} from './orientation-contact-sheets.mjs';

const CONTRACT = { modelCount: 2, taskCount: 2, successCount: 3, failureCount: 1 };

async function png(color) {
  return sharp({ create: { width: 40, height: 32, channels: 4, background: color } }).png().toBuffer();
}

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), 'orientation-sheets-test-'));
  const references = path.join(root, 'references');
  const candidates = path.join(root, 'search-output');
  const output = path.join(root, 'published');
  await mkdir(references, { recursive: true });
  await mkdir(candidates, { recursive: true });
  const models = ['model-b', 'model-a'];
  const tasks = [
    { id: 'task-z', image: 'references/task-z.png' },
    { id: 'task-a', image: 'references/task-a.png' },
  ];
  await Promise.all(tasks.map(async ({ id }, index) => {
    await writeFile(path.join(references, `${id}.png`), await png(index ? '#22c55e' : '#ef4444'));
  }));
  const cells = [];
  for (const [taskIndex, task] of tasks.entries()) {
    for (const [modelIndex, modelId] of models.entries()) {
      if (modelId === 'model-a' && task.id === 'task-a') continue;
      const relative = `${modelId}/${task.id}/top.png`;
      const absolute = path.join(candidates, relative);
      await mkdir(path.dirname(absolute), { recursive: true });
      await writeFile(absolute, await png(taskIndex ? '#38bdf8' : modelIndex ? '#f59e0b' : '#a855f7'));
      cells.push({
        modelId,
        taskId: task.id,
        status: 'ranked',
        margin: 0.1 + modelIndex / 10,
        ambiguous: false,
        top: [{ rank: 1, id: 'x0:y0:z0', rotation: { x: 0, y: 0, z: 0 }, scores: { total: 0.9, iou: 0.8, edgeF1: 0.7, spatial: 0.6 }, file: relative }],
      });
    }
  }
  const report = {
    schemaVersion: 1,
    ok: true,
    output: candidates,
    expectedFailures: ['model-a/task-a'],
    inventory: { modelCount: 2, taskCount: 2, successCellCount: 3, expectedFailureCount: 1, selectedSuccessCellCount: 3 },
    cells,
  };
  const modelsPath = path.join(root, 'models.json');
  const tasksPath = path.join(root, 'tasks.json');
  const reportPath = path.join(root, 'report.json');
  await Promise.all([
    writeFile(modelsPath, JSON.stringify(models)),
    writeFile(tasksPath, JSON.stringify(tasks)),
    writeFile(reportPath, JSON.stringify(report)),
  ]);
  return { root, references, candidates, output, modelsPath, tasksPath, reportPath, report };
}

function paths(value) {
  return { searchReport: value.reportPath, references: value.references, models: value.modelsPath, tasks: value.tasksPath, output: value.output };
}

test('strict CLI requires each option exactly once', () => {
  const parsed = parseContactSheetArgs([
    '--search-report', 'report.json', '--references', 'refs', '--models', 'models.json', '--tasks', 'tasks.json', '--output', 'out',
  ]);
  assert.equal(path.isAbsolute(parsed.output), true);
  assert.throws(() => parseContactSheetArgs([]), /missing required option/);
  assert.throws(() => parseContactSheetArgs(['--search-report', 'a', '--search-report', 'b']), /duplicate option/);
  assert.throws(() => parseContactSheetArgs(['--unknown', 'x']), /unknown option/);
});

test('generates fixed sheets and deterministic index in registry order', async () => {
  const value = await fixture();
  try {
    const index = await generateOrientationContactSheets(paths(value), CONTRACT);
    assert.deepEqual(index.tasks.map(({ task }) => task), ['task-z', 'task-a']);
    assert.deepEqual(index.tasks[0].panels.map(({ source }) => source), [
      'references/task-z.png', 'model-b/task-z/top.png', 'model-a/task-z/top.png',
    ]);
    assert.equal(index.tasks[1].panels[2].source, null);
    for (const task of index.tasks) {
      const bytes = await readFile(path.join(value.output, task.file));
      const metadata = await sharp(bytes).metadata();
      assert.equal(metadata.width, SHEET_COLUMNS * PANEL_WIDTH);
      assert.equal(metadata.height, SHEET_ROWS * PANEL_HEIGHT);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), task.sha256);
    }
    assert.deepEqual(JSON.parse(await readFile(path.join(value.output, 'index.json'), 'utf8')), index);
  } finally {
    await rm(value.root, { recursive: true, force: true });
  }
});

test('missing source and report drift fail without replacing published output', async () => {
  const value = await fixture();
  try {
    await mkdir(value.output);
    await writeFile(path.join(value.output, 'sentinel.txt'), 'keep');
    await rm(path.join(value.candidates, value.report.cells[0].top[0].file));
    await assert.rejects(generateOrientationContactSheets(paths(value), CONTRACT), /candidate .* is missing/);
    assert.equal(await readFile(path.join(value.output, 'sentinel.txt'), 'utf8'), 'keep');

    const candidate = value.report.cells[0];
    const absolute = path.join(value.candidates, candidate.top[0].file);
    await mkdir(path.dirname(absolute), { recursive: true });
    await writeFile(absolute, await png('#ffffff'));
    value.report.cells.pop();
    await writeFile(value.reportPath, JSON.stringify(value.report));
    await assert.rejects(generateOrientationContactSheets(paths(value), CONTRACT), /exactly 3 ranked cells/);
    assert.equal(await readFile(path.join(value.output, 'sentinel.txt'), 'utf8'), 'keep');
  } finally {
    await rm(value.root, { recursive: true, force: true });
  }
});
