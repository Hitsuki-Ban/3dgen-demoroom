import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { parseModelRegistry, parseTasks, renderFingerprint, sha256, stableStringify } from './thumbnail-batch-lib.mjs';
import { parseOrientationFixes } from './orientation-fixes-lib.mjs';
import { generateOrientationCandidates, writeJsonAtomic } from './orientation-search-lib.mjs';

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const repositoryRoot = path.resolve(webRoot, '..');

function sameRotation(left, right) {
  return ['x', 'y', 'z'].every((axis) => left?.[axis] === right?.[axis]);
}

function validateRankedCandidates(cell, key) {
  const expected = generateOrientationCandidates(cell.modelId);
  if (cell.candidateCount !== expected.length || !Array.isArray(cell.rankedCandidates) || cell.rankedCandidates.length !== expected.length) {
    throw new TypeError(`search report cell ${key} lacks complete ranked candidate evidence`);
  }
  const expectedById = new Map(expected.map((candidate) => [candidate.id, candidate.rotation]));
  const seen = new Set();
  cell.rankedCandidates.forEach((candidate, index) => {
    if (candidate?.rank !== index + 1) throw new TypeError(`search report cell ${key} candidate ranks must be contiguous`);
    if (typeof candidate.id !== 'string' || !expectedById.has(candidate.id)) {
      throw new TypeError(`search report cell ${key} contains unknown candidate ${candidate?.id}`);
    }
    if (seen.has(candidate.id)) throw new TypeError(`search report cell ${key} contains duplicate candidate ${candidate.id}`);
    seen.add(candidate.id);
    if (!sameRotation(candidate.rotation, expectedById.get(candidate.id))) {
      throw new TypeError(`search report cell ${key} candidate ${candidate.id} rotation differs`);
    }
    const scoreKeys = Object.keys(candidate.scores ?? {}).sort();
    if (scoreKeys.join(',') !== 'edgeF1,iou,spatial,total') {
      throw new TypeError(`search report cell ${key} candidate ${candidate.id} scores differ`);
    }
    for (const score of Object.values(candidate.scores)) {
      if (typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > 1) {
        throw new TypeError(`search report cell ${key} candidate ${candidate.id} score is invalid`);
      }
    }
  });
  if (seen.size !== expectedById.size) throw new TypeError(`search report cell ${key} lacks complete candidate rotations`);
}

function strictReportCells(report, modelIds, taskIds, expectedFailures) {
  if (report?.schemaVersion !== 1 || report.ok !== true || !Array.isArray(report.cells)) {
    throw new TypeError('search report must be a successful schemaVersion 1 report');
  }
  const expected = new Set(modelIds.flatMap((modelId) => taskIds.map((taskId) => `${modelId}/${taskId}`)).filter((key) => !expectedFailures.has(key)));
  if (report.cells.length !== expected.size) throw new TypeError(`search report must contain exactly ${expected.size} success cells`);
  const cells = new Map();
  for (const cell of report.cells) {
    const key = `${cell?.modelId}/${cell?.taskId}`;
    if (!expected.has(key)) throw new TypeError(`search report contains unknown cell ${key}`);
    if (cells.has(key)) throw new TypeError(`search report contains duplicate cell ${key}`);
    if (cell.status !== 'ranked') throw new TypeError(`search report cell ${key} must be ranked`);
    validateRankedCandidates(cell, key);
    cells.set(key, cell);
  }
  for (const key of expected) if (!cells.has(key)) throw new TypeError(`search report is missing cell ${key}`);
  return cells;
}

export function buildSelectedEvidence({ report, reportText, fixes, modelIds, taskIds, expectedFailures }) {
  const reportCells = strictReportCells(report, modelIds, taskIds, expectedFailures);
  const cells = {};
  for (const modelId of modelIds) {
    for (const taskId of taskIds) {
      const key = `${modelId}/${taskId}`;
      const fix = fixes.cells[key];
      if (expectedFailures.has(key)) {
        cells[key] = fix;
        continue;
      }
      const source = reportCells.get(key);
      const selected = source.rankedCandidates.find((candidate) => sameRotation(candidate.rotation, fix.rotationDegrees));
      if (!selected) throw new TypeError(`${key} selected rotation is absent from complete search evidence`);
      const geometryLimited = fix.provenance.kind === 'manual' && fix.provenance.reason.includes('source geometry is incomplete');
      const provenance = fix.provenance.kind === 'auto' && selected.rank === 1
        ? { kind: 'auto', score: selected.scores.total, margin: source.margin, reviewed: true }
        : {
            kind: 'manual',
            reason: geometryLimited
              ? `visual review selected rank ${selected.rank}; source geometry is incomplete, so this is the best available reference-facing orientation`
              : `visual review selected rank ${selected.rank} to match the reference-facing direction`,
            reviewed: true,
          };
      cells[key] = {
        status: 'fixed',
        selection: { rank: selected.rank, rotationDegrees: selected.rotation, scores: selected.scores, margin: source.margin },
        source: source.source,
        referenceMask: source.referenceMask,
        provenance,
      };
    }
  }
  return {
    schemaVersion: 1,
    searchReport: {
      sha256: createHash('sha256').update(reportText.replace(/\r\n/g, '\n')).digest('hex'),
      recipeSha256: sha256(stableStringify(report.recipe)),
      rendererFingerprint: renderFingerprint(report.recipe.renderer),
    },
    modelOrder: modelIds,
    taskOrder: taskIds,
    expectedFailures: [...expectedFailures].sort(),
    cells,
  };
}

export async function main() {
  const reportPath = path.join(repositoryRoot, 'outputs/issue-85/search-centered-report.json');
  const [models, tasks, reportText, fixesText] = await Promise.all([
    readFile(path.join(webRoot, 'src/data/model-registry.json'), 'utf8').then(JSON.parse),
    readFile(path.join(repositoryRoot, 'tasks/tasks.json'), 'utf8').then(JSON.parse),
    readFile(reportPath, 'utf8'),
    readFile(path.join(webRoot, 'src/data/orientation-fixes.json'), 'utf8'),
  ]);
  const modelIds = parseModelRegistry(models);
  const taskIds = parseTasks(tasks);
  const expectedFailures = new Set(['partcrafter/chrome-espresso-machine']);
  const fixes = parseOrientationFixes(fixesText, { modelIds, taskIds, expectedFailures });
  const evidence = buildSelectedEvidence({
    report: JSON.parse(reportText), reportText, fixes, modelIds, taskIds, expectedFailures,
  });
  await writeJsonAtomic(path.join(webRoot, 'src/data/orientation-selected-evidence.json'), evidence);
  process.stdout.write(`wrote ${Object.keys(evidence.cells).length} selected evidence records\n`);
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) await main();
