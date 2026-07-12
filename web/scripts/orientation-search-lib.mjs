import { createHash } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import { GetObjectCommand } from '@aws-sdk/client-s3';
import { Euler, MathUtils, Quaternion } from 'three';

import {
  formatIfMatch,
  listSiteDataObjects,
  normalizeEtag,
  parseExpectedFailures,
  parseS3Root,
  reconcileInventory,
  selectSuccessCells,
  sha256,
  stableStringify,
} from './thumbnail-batch-lib.mjs';
import {
  AMBIGUITY_MARGIN,
  NORMALIZED_SIZE,
  extractCandidateFeatures,
  extractReferenceMaskFeatures,
  rankOrientations,
} from './orientation-scoring.mjs';

const SAFE_ID = /^[a-z0-9-]+$/;
const TOP_COUNT = 5;
const TILTED_MODELS = new Set(['triposr', '3dtopia-xl']);
const TILT_DEGREES = Object.freeze([-90, -45, 0, 45, 90]);

export const ORIENTATION_SEARCH_RECIPE = Object.freeze({
  schemaVersion: 2,
  rotationMode: 'absolute-euler-degrees',
  eulerOrder: 'XYZ',
  canonicalRange: '[-180,180)',
  standard: Object.freeze({ pitch: Object.freeze([0]), roll: Object.freeze([0]), yawStep: 15 }),
  tilted: Object.freeze({ pitch: TILT_DEGREES, roll: TILT_DEGREES, yawStep: 30 }),
  topCount: TOP_COUNT,
  scoring: Object.freeze({ normalizedSize: NORMALIZED_SIZE, ambiguityMargin: AMBIGUITY_MARGIN }),
});

function requireValue(argv, index, option) {
  const value = argv[index + 1];
  if (!value || value.startsWith('--')) throw new Error(`${option} requires a value`);
  return value;
}

function setOnce(target, key, value, option) {
  if (target[key] !== null) throw new Error(`${option} may only be provided once`);
  target[key] = value;
}

function requireSafeId(value, option) {
  if (value !== null && !SAFE_ID.test(value)) throw new Error(`${option} must match [a-z0-9-]+`);
}

export function parseOrientationSearchArgs(argv) {
  if (!Array.isArray(argv)) throw new Error('orientation search arguments must be an array');
  const parsed = {
    r2Root: null,
    output: null,
    referenceMaskRoot: null,
    report: null,
    backend: null,
    model: null,
    task: null,
    reviewAllCandidates: false,
    expectedFailureValues: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (option === '--r2-root') {
      setOnce(parsed, 'r2Root', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--output') {
      setOnce(parsed, 'output', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--reference-mask-root') {
      setOnce(parsed, 'referenceMaskRoot', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--report') {
      setOnce(parsed, 'report', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--backend') {
      setOnce(parsed, 'backend', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--model') {
      setOnce(parsed, 'model', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--task') {
      setOnce(parsed, 'task', requireValue(argv, index, option), option);
      index += 1;
    } else if (option === '--expected-failure') {
      parsed.expectedFailureValues.push(requireValue(argv, index, option));
      index += 1;
    } else if (option === '--review-all-candidates') {
      if (parsed.reviewAllCandidates) throw new Error('--review-all-candidates may only be provided once');
      parsed.reviewAllCandidates = true;
    } else {
      throw new Error(`unknown orientation search argument: ${option}`);
    }
  }

  for (const [option, key] of [
    ['--r2-root', 'r2Root'],
    ['--output', 'output'],
    ['--reference-mask-root', 'referenceMaskRoot'],
    ['--report', 'report'],
    ['--backend', 'backend'],
  ]) {
    if (parsed[key] === null) throw new Error(`${option} is required`);
  }
  if (!['swiftshader', 'gpu'].includes(parsed.backend)) {
    throw new Error(`--backend must be swiftshader or gpu, received: ${parsed.backend}`);
  }
  requireSafeId(parsed.model, '--model');
  requireSafeId(parsed.task, '--task');
  parsed.r2RootValue = parsed.r2Root;
  parsed.r2Root = parseS3Root(parsed.r2Root);
  parsed.expectedFailures = parseExpectedFailures(parsed.expectedFailureValues, { requireAtLeastOne: true });
  delete parsed.expectedFailureValues;
  return parsed;
}

export function canonicalDegrees(value) {
  if (!Number.isFinite(value)) throw new Error('candidate rotation must contain finite degrees');
  const canonical = ((value + 180) % 360 + 360) % 360 - 180;
  return Object.is(canonical, -0) ? 0 : canonical;
}

function quaternionKey(rotation) {
  const quaternion = new Quaternion().setFromEuler(
    new Euler(
      MathUtils.degToRad(rotation.x),
      MathUtils.degToRad(rotation.y),
      MathUtils.degToRad(rotation.z),
      'XYZ',
    ),
  ).normalize();
  if (quaternion.w < 0) quaternion.set(-quaternion.x, -quaternion.y, -quaternion.z, -quaternion.w);
  return quaternion.toArray().map((value) => value.toFixed(10)).join(',');
}

function rotationId(rotation) {
  return `x${rotation.x}:y${rotation.y}:z${rotation.z}`;
}

export function generateOrientationCandidates(modelId) {
  if (typeof modelId !== 'string' || !SAFE_ID.test(modelId)) throw new Error('model ID must match [a-z0-9-]+');
  const tilted = TILTED_MODELS.has(modelId);
  const pitches = tilted ? TILT_DEGREES : [0];
  const rolls = tilted ? TILT_DEGREES : [0];
  const yawStep = tilted ? 30 : 15;
  const candidates = [];
  const quaternionKeys = new Set();
  for (const xValue of pitches) {
    for (const zValue of rolls) {
      for (let yValue = 0; yValue < 360; yValue += yawStep) {
        const rotation = Object.freeze({
          x: canonicalDegrees(xValue),
          y: canonicalDegrees(yValue),
          z: canonicalDegrees(zValue),
        });
        const key = quaternionKey(rotation);
        if (quaternionKeys.has(key)) continue;
        quaternionKeys.add(key);
        candidates.push(Object.freeze({ id: rotationId(rotation), rotation }));
      }
    }
  }
  return Object.freeze(candidates);
}

function bodyAsReadable(body) {
  if (body instanceof Uint8Array) return Readable.from([body]);
  if (body && typeof body[Symbol.asyncIterator] === 'function') return body;
  if (body && typeof body.getReader === 'function') return Readable.fromWeb(body);
  throw new Error('R2 GetObject response Body is not a readable byte stream');
}

async function downloadSource(client, bucket, source, outputPath) {
  const response = await client.send(new GetObjectCommand({
    Bucket: bucket,
    Key: source.key,
    IfMatch: source.ifMatch ?? formatIfMatch(source.etag),
  }));
  if (normalizeEtag(response.ETag) !== source.etag) throw new Error(`source ETag changed during download: ${source.key}`);
  if (response.ContentLength !== source.size) {
    throw new Error(`source ContentLength changed during download: ${source.key}`);
  }
  if (!response.Body) throw new Error(`source GetObject response has no Body: ${source.key}`);
  const digest = createHash('sha256');
  let downloadedSize = 0;
  const tap = new Transform({
    transform(chunk, _encoding, callback) {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      downloadedSize += bytes.length;
      digest.update(bytes);
      callback(null, bytes);
    },
  });
  await pipeline(bodyAsReadable(response.Body), tap, createWriteStream(outputPath, { flags: 'w' }));
  if (downloadedSize !== source.size) {
    throw new Error(`source byte count differs: ${source.key} expected ${source.size}, received ${downloadedSize}`);
  }
  return { size: downloadedSize, sha256: digest.digest('hex') };
}

function safeError(error) {
  return { name: error instanceof Error ? error.name : 'Error', message: error instanceof Error ? error.message : String(error) };
}

function reportPath(outputRoot, filePath) {
  return path.relative(outputRoot, filePath).replaceAll(path.sep, '/');
}

function rotationSlug(rotation) {
  const part = (axis, value) => `${axis}${value < 0 ? 'm' : 'p'}${Math.abs(value)}`;
  return `${part('x', rotation.x)}-${part('y', rotation.y)}-${part('z', rotation.z)}`;
}

async function saveCaptureAtomically(session, pngPath, destination, rotation) {
  await session.capture({ outputPath: pngPath, orientationDegrees: rotation });
  await mkdir(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, await readFile(pngPath), { flag: 'wx' });
    await rm(destination, { force: true });
    await rename(temporary, destination);
  } finally {
    await rm(temporary, { force: true });
  }
}

export function formatTopCandidates(ranking, candidateById, count = TOP_COUNT) {
  if (!ranking || !Array.isArray(ranking.ranked)) throw new Error('orientation ranking is invalid');
  return ranking.ranked.slice(0, count).map((ranked, index) => {
    const candidate = candidateById.get(ranked.id);
    if (!candidate) throw new Error(`ranked orientation is missing candidate: ${ranked.id}`);
    return {
      rank: index + 1,
      id: ranked.id,
      rotation: candidate.rotation,
      scores: { total: ranked.total, iou: ranked.iou, edgeF1: ranked.edgeF1, spatial: ranked.spatial },
    };
  });
}

export async function writeJsonAtomic(filePath, value) {
  const absolute = path.resolve(filePath);
  await mkdir(path.dirname(absolute), { recursive: true });
  const temporary = `${absolute}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    await rm(absolute, { force: true });
    await rename(temporary, absolute);
  } finally {
    await rm(temporary, { force: true });
  }
}

export async function runOrientationSearch({
  client,
  bucket,
  prefix,
  modelIds,
  taskIds,
  expectedFailures,
  model = null,
  task = null,
  backend,
  outputRoot,
  referenceMaskRoot,
  createRenderer,
  report,
  temporaryParent = tmpdir(),
  listObjects = listSiteDataObjects,
  extractReference = extractReferenceMaskFeatures,
  extractCandidate = extractCandidateFeatures,
  rankCandidates = rankOrientations,
  reviewAllCandidates = false,
  onProgress = () => {},
}) {
  if (!report || typeof report !== 'object' || Array.isArray(report)) throw new Error('orientation report object is required');
  if (typeof createRenderer !== 'function') throw new Error('orientation renderer factory is required');
  const absoluteOutput = path.resolve(outputRoot);
  const absoluteMasks = path.resolve(referenceMaskRoot);
  const objects = await listObjects(client, { bucket, prefix });
  const inventory = reconcileInventory({ objects, modelIds, taskIds, expectedFailures, prefix });
  const selected = selectSuccessCells(inventory.successCells, { model, task, modelIds, taskIds });
  report.inventory = {
    modelCount: modelIds.length,
    taskCount: taskIds.length,
    objectCount: inventory.objectCount,
    successCellCount: inventory.successCells.length,
    expectedFailureCount: inventory.failureCells.length,
    selectedSuccessCellCount: selected.length,
  };
  report.cells = [];
  report.errors = [];

  const temporaryDirectory = await mkdtemp(path.join(temporaryParent, '3dgen-orientation-search-'));
  const glbPath = path.join(temporaryDirectory, 'source.glb');
  const pngPath = path.join(temporaryDirectory, 'candidate.png');
  const referenceCache = new Map();
  let renderer;
  const cellErrors = [];
  let operationError = null;
  try {
    renderer = await createRenderer({ backend });
    if (!renderer || typeof renderer.openSession !== 'function' || typeof renderer.close !== 'function') {
      throw new Error('orientation renderer must expose openSession() and close()');
    }
    report.recipe = {
      search: {
        ...ORIENTATION_SEARCH_RECIPE,
        savedCandidateCount: reviewAllCandidates ? 'all' : TOP_COUNT,
      },
      scoringImplementationSha256: sha256(await readFile(new URL('./orientation-scoring.mjs', import.meta.url))),
      renderer: renderer.recipe,
      backend,
    };

    for (const cell of selected) {
      const cellReport = {
        modelId: cell.modelId,
        taskId: cell.taskId,
        status: 'running',
        source: { key: cell.source.key, etag: cell.source.etag, size: cell.source.size },
      };
      report.cells.push(cellReport);
      let session;
      try {
        onProgress(`${cell.modelId}/${cell.taskId}: download`);
        await rm(glbPath, { force: true });
        const downloaded = await downloadSource(client, bucket, cell.source, glbPath);
        cellReport.source.sha256 = downloaded.sha256;

        let reference = referenceCache.get(cell.taskId);
        if (!reference) {
          const referencePath = path.join(absoluteMasks, `${cell.taskId}.png`);
          const referenceStats = await stat(referencePath);
          if (!referenceStats.isFile() || referenceStats.size === 0) {
            throw new Error(`reference mask is missing or empty: ${referencePath}`);
          }
          const bytes = await readFile(referencePath);
          reference = { features: await extractReference(bytes), sha256: sha256(bytes), file: `${cell.taskId}.png` };
          referenceCache.set(cell.taskId, reference);
        }
        cellReport.referenceMask = { file: reference.file, sha256: reference.sha256 };

        const candidates = generateOrientationCandidates(cell.modelId);
        const candidateById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
        const scoredCandidates = [];
        session = await renderer.openSession({ glbPath, modelId: cell.modelId, taskId: cell.taskId });
        for (const candidate of candidates) {
          const capture = await session.capture({ outputPath: pngPath, orientationDegrees: candidate.rotation });
          if (capture?.width !== 320 || capture?.height !== 320) {
            throw new Error(`candidate capture must be 320x320: ${candidate.id}`);
          }
          scoredCandidates.push({ id: candidate.id, features: await extractCandidate(pngPath) });
        }
        const ranking = rankCandidates(reference.features, scoredCandidates);
        const rankedCandidates = formatTopCandidates(ranking, candidateById, candidates.length);
        const top = formatTopCandidates(
          ranking,
          candidateById,
          reviewAllCandidates ? candidates.length : TOP_COUNT,
        );
        const cellOutput = path.join(absoluteOutput, 'candidates', cell.modelId, cell.taskId);
        await rm(cellOutput, { recursive: true, force: true });
        for (const candidate of top) {
          const destination = path.join(
            cellOutput,
            `${String(candidate.rank).padStart(2, '0')}-${rotationSlug(candidate.rotation)}.png`,
          );
          await saveCaptureAtomically(session, pngPath, destination, candidate.rotation);
          candidate.file = reportPath(absoluteOutput, destination);
        }
        cellReport.status = 'ranked';
        cellReport.candidateCount = candidates.length;
        cellReport.margin = ranking.margin;
        cellReport.ambiguous = ranking.ambiguous;
        cellReport.renderer = { webglRenderer: session.webglRenderer, stats: session.stats };
        cellReport.rankedCandidates = rankedCandidates;
        cellReport.top = top;
        onProgress(`${cell.modelId}/${cell.taskId}: ranked ${candidates.length} candidates`);
      } catch (error) {
        const detail = safeError(error);
        cellReport.status = 'failed';
        cellReport.error = detail;
        report.errors.push({ modelId: cell.modelId, taskId: cell.taskId, ...detail });
        cellErrors.push(new Error(`${cell.modelId}/${cell.taskId}: ${detail.message}`, { cause: error }));
        onProgress(`${cell.modelId}/${cell.taskId}: failed: ${detail.message}`);
      } finally {
        if (session) {
          try {
            await session.close();
          } catch (error) {
            const detail = safeError(error);
            cellReport.status = 'failed';
            cellReport.error = detail;
            report.errors.push({ modelId: cell.modelId, taskId: cell.taskId, phase: 'session-close', ...detail });
            cellErrors.push(new Error(`${cell.modelId}/${cell.taskId} session close: ${detail.message}`, { cause: error }));
          }
        }
      }
    }
    if (cellErrors.length > 0) throw new AggregateError(cellErrors, `${cellErrors.length} orientation cell(s) failed`);
    return report;
  } catch (error) {
    operationError = error;
    throw error;
  } finally {
    const cleanupErrors = [];
    try {
      await renderer?.close();
    } catch (error) {
      cleanupErrors.push(error);
    }
    try {
      await rm(temporaryDirectory, { recursive: true, force: true });
    } catch (error) {
      cleanupErrors.push(error);
    }
    if (cleanupErrors.length > 0) {
      if (operationError) throw new AggregateError([operationError, ...cleanupErrors], 'orientation search and cleanup failed');
      throw new AggregateError(cleanupErrors, 'orientation search cleanup failed');
    }
  }
}

export function orientationRecipeFingerprint(rendererRecipe, backend) {
  return sha256(stableStringify({ search: ORIENTATION_SEARCH_RECIPE, renderer: rendererRecipe, backend }));
}
