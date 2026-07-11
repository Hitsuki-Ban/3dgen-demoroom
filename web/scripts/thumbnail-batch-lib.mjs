import { createHash } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { mkdtemp, readFile, rm, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import {
  GetObjectCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
} from '@aws-sdk/client-s3';
import sharp from 'sharp';

export const THUMBNAIL_SIZE = 320;
export const THUMBNAIL_CACHE_CONTROL = 'public, max-age=300, stale-while-revalidate=86400';
const SAFE_ID = /^[a-z0-9-]+$/;
const SHA256 = /^[a-f0-9]{64}$/;
const ALLOWED_CELL_FILES = new Set(['failure.json', 'meta.json', 'output.glb', 'thumb.webp']);
const REQUIRED_ENV = ['R2_ENDPOINT', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'];

function requireOptionValue(argv, index, option) {
  const value = argv[index + 1];
  if (!value || value.startsWith('--')) throw new Error(`${option} requires a value`);
  return value;
}

function setOnce(parsed, key, value, option) {
  if (parsed[key] !== null) throw new Error(`${option} may only be provided once`);
  parsed[key] = value;
}

export function parseExpectedFailures(values, { requireAtLeastOne = false } = {}) {
  const failures = new Set();
  for (const value of values) {
    const parts = value.split('/');
    if (parts.length !== 2 || !parts.every((part) => SAFE_ID.test(part))) {
      throw new Error(`expected failure must be MODEL_ID/TASK_ID, received: ${value}`);
    }
    if (failures.has(value)) throw new Error(`duplicate expected failure: ${value}`);
    failures.add(value);
  }
  if (requireAtLeastOne && failures.size === 0) {
    throw new Error('at least one explicit --expected-failure MODEL_ID/TASK_ID is required');
  }
  return failures;
}

export function parseS3Root(value) {
  const match = /^s3:\/\/([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])\/site-data$/.exec(value);
  if (!match) throw new Error('R2 root must be exactly s3://BUCKET/site-data');
  return { bucket: match[1], prefix: 'site-data' };
}

export function parseCliArgs(argv) {
  const parsed = {
    s3Root: null,
    model: null,
    task: null,
    backend: null,
    report: null,
    check: false,
    force: false,
    expectedFailureValues: [],
  };
  const positional = [];

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--') continue;
    if (argument === '--expected-failure') {
      parsed.expectedFailureValues.push(requireOptionValue(argv, index, argument));
      index += 1;
    } else if (argument === '--model') {
      setOnce(parsed, 'model', requireOptionValue(argv, index, argument), argument);
      index += 1;
    } else if (argument === '--task') {
      setOnce(parsed, 'task', requireOptionValue(argv, index, argument), argument);
      index += 1;
    } else if (argument === '--backend') {
      setOnce(parsed, 'backend', requireOptionValue(argv, index, argument), argument);
      index += 1;
    } else if (argument === '--report') {
      setOnce(parsed, 'report', requireOptionValue(argv, index, argument), argument);
      index += 1;
    } else if (argument === '--check') {
      if (parsed.check) throw new Error('--check may only be provided once');
      parsed.check = true;
    } else if (argument === '--force') {
      if (parsed.force) throw new Error('--force may only be provided once');
      parsed.force = true;
    } else if (argument.startsWith('--')) {
      throw new Error(`unknown thumbnail batch argument: ${argument}`);
    } else {
      positional.push(argument);
    }
  }

  if (positional.length !== 1) throw new Error('exactly one s3://BUCKET/site-data argument is required');
  parsed.s3Root = parseS3Root(positional[0]);
  parsed.backend ??= 'swiftshader';
  if (!['swiftshader', 'gpu'].includes(parsed.backend)) {
    throw new Error(`--backend must be swiftshader or gpu, received: ${parsed.backend}`);
  }
  for (const [option, value] of [
    ['--model', parsed.model],
    ['--task', parsed.task],
  ]) {
    if (value !== null && !SAFE_ID.test(value)) throw new Error(`${option} must match [a-z0-9-]+`);
  }
  if (parsed.check && parsed.force) throw new Error('--check and --force are mutually exclusive');
  parsed.expectedFailures = parseExpectedFailures(parsed.expectedFailureValues, { requireAtLeastOne: true });
  delete parsed.expectedFailureValues;
  return parsed;
}

export function requireR2Environment(environment) {
  const missing = REQUIRED_ENV.filter((name) => !environment[name]?.trim());
  if (missing.length > 0) throw new Error(`missing required R2 environment variable(s): ${missing.join(', ')}`);
  const endpoint = new URL(environment.R2_ENDPOINT);
  if (
    endpoint.protocol !== 'https:' ||
    endpoint.username ||
    endpoint.password ||
    endpoint.pathname !== '/' ||
    endpoint.search ||
    endpoint.hash
  ) {
    throw new Error('R2_ENDPOINT must be an HTTPS origin without credentials, path, query, or fragment');
  }
  return {
    endpoint: endpoint.href.replace(/\/$/, ''),
    accessKeyId: environment.R2_ACCESS_KEY_ID,
    secretAccessKey: environment.R2_SECRET_ACCESS_KEY,
  };
}

function validateIdList(values, label) {
  if (!Array.isArray(values) || values.length === 0) throw new Error(`${label} must be a non-empty array`);
  const ids = [];
  const seen = new Set();
  for (const value of values) {
    if (typeof value !== 'string' || !SAFE_ID.test(value)) throw new Error(`${label} IDs must match [a-z0-9-]+`);
    if (seen.has(value)) throw new Error(`${label} contains duplicate ID: ${value}`);
    seen.add(value);
    ids.push(value);
  }
  return ids;
}

export function parseModelRegistry(payload) {
  return validateIdList(payload, 'model registry');
}

export function parseTasks(payload) {
  if (!Array.isArray(payload) || payload.length === 0) throw new Error('tasks must be a non-empty array');
  return validateIdList(
    payload.map((task, index) => {
      if (!task || typeof task !== 'object' || Array.isArray(task)) throw new Error(`tasks[${index}] must be an object`);
      return task.id;
    }),
    'tasks',
  );
}

export async function listSiteDataObjects(client, { bucket, prefix }) {
  const objects = [];
  const keys = new Set();
  const tokens = new Set();
  let continuationToken;

  do {
    const response = await client.send(
      new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: `${prefix}/`,
        ...(continuationToken ? { ContinuationToken: continuationToken } : {}),
      }),
    );
    for (const object of response.Contents ?? []) {
      if (typeof object.Key !== 'string' || !object.Key) throw new Error('R2 inventory object is missing Key');
      if (!Number.isSafeInteger(object.Size) || object.Size <= 0) {
        throw new Error(`R2 inventory object must have a positive safe Size: ${object.Key}`);
      }
      if (typeof object.ETag !== 'string' || !object.ETag.trim()) {
        throw new Error(`R2 inventory object is missing ETag: ${object.Key}`);
      }
      if (keys.has(object.Key)) throw new Error(`R2 inventory contains duplicate key: ${object.Key}`);
      keys.add(object.Key);
      objects.push({ key: object.Key, size: object.Size, etag: object.ETag });
    }

    if (!response.IsTruncated) break;
    continuationToken = response.NextContinuationToken;
    if (!continuationToken) throw new Error('truncated R2 inventory response is missing NextContinuationToken');
    if (tokens.has(continuationToken)) throw new Error('R2 inventory pagination repeated a continuation token');
    tokens.add(continuationToken);
  } while (true);

  return objects;
}

export function normalizeEtag(value) {
  if (typeof value !== 'string') throw new Error('ETag must be a string');
  let etag = value.trim();
  if (etag.startsWith('W/')) throw new Error(`weak ETag is not valid for R2 object publication: ${value}`);
  if (etag.startsWith('"') || etag.endsWith('"')) {
    if (!(etag.startsWith('"') && etag.endsWith('"') && etag.length > 2)) {
      throw new Error(`malformed ETag: ${value}`);
    }
    etag = etag.slice(1, -1);
  }
  if (!etag || /["\x00-\x1f\x7f]/.test(etag)) throw new Error(`malformed ETag: ${value}`);
  return etag;
}

export function formatIfMatch(value) {
  return `"${normalizeEtag(value)}"`;
}

export function thumbnailWriteCondition(existingEtag) {
  return existingEtag ? { IfMatch: formatIfMatch(existingEtag) } : { IfNoneMatch: '*' };
}

function cellName(modelId, taskId) {
  return `${modelId}/${taskId}`;
}

export function reconcileInventory({ objects, modelIds, taskIds, expectedFailures, prefix = 'site-data' }) {
  const models = new Set(modelIds);
  const tasks = new Set(taskIds);
  const expectedCells = new Set(modelIds.flatMap((modelId) => taskIds.map((taskId) => cellName(modelId, taskId))));
  for (const failure of expectedFailures) {
    if (!expectedCells.has(failure)) throw new Error(`expected failure references unknown cell: ${failure}`);
  }

  const filesByCell = new Map([...expectedCells].map((cell) => [cell, new Map()]));
  const escapedPrefix = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const keyPattern = new RegExp(`^${escapedPrefix}/([^/]+)/([^/]+)/(.*)$`);

  for (const object of objects) {
    const match = keyPattern.exec(object.key);
    if (!match) throw new Error(`unexpected object under ${prefix}/: ${object.key}`);
    const [, modelId, taskId, relativePath] = match;
    if (!models.has(modelId) || !tasks.has(taskId)) throw new Error(`object references unknown cell: ${object.key}`);
    if (relativePath === 'LICENSE' || relativePath === 'LICENSES.txt' || relativePath.startsWith('raw/')) continue;
    const fileName = relativePath;
    if (!ALLOWED_CELL_FILES.has(fileName)) throw new Error(`unexpected site-data cell file: ${object.key}`);
    const files = filesByCell.get(cellName(modelId, taskId));
    if (files.has(fileName)) throw new Error(`duplicate site-data cell file: ${object.key}`);
    files.set(fileName, object);
  }

  const successCells = [];
  const failureCells = [];
  for (const modelId of modelIds) {
    for (const taskId of taskIds) {
      const name = cellName(modelId, taskId);
      const files = filesByCell.get(name);
      const actual = [...files.keys()].sort();
      if (expectedFailures.has(name)) {
        if (actual.length !== 1 || actual[0] !== 'failure.json') {
          throw new Error(`expected failure cell ${name} must contain only failure.json; received [${actual.join(', ')}]`);
        }
        failureCells.push({ modelId, taskId, failure: files.get('failure.json') });
        continue;
      }

      if (!files.has('meta.json') || !files.has('output.glb') || files.has('failure.json')) {
        throw new Error(
          `success cell ${name} must contain meta.json and output.glb without failure.json; received [${actual.join(', ')}]`,
        );
      }
      const source = files.get('output.glb');
      successCells.push({
        modelId,
        taskId,
        source: {
          key: source.key,
          size: source.size,
          etag: normalizeEtag(source.etag),
          ifMatch: formatIfMatch(source.etag),
        },
        thumbnailKey: `${prefix}/${modelId}/${taskId}/thumb.webp`,
      });
    }
  }
  return { successCells, failureCells, objectCount: objects.length };
}

export function selectSuccessCells(cells, { model = null, task = null, modelIds, taskIds }) {
  if (model !== null && !modelIds.includes(model)) throw new Error(`--model references unknown model: ${model}`);
  if (task !== null && !taskIds.includes(task)) throw new Error(`--task references unknown task: ${task}`);
  const selected = cells.filter(
    (cell) => (model === null || cell.modelId === model) && (task === null || cell.taskId === task),
  );
  if (selected.length === 0) throw new Error('thumbnail selection contains no successful cells');
  return selected;
}

export function stableStringify(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('render recipe may not contain a non-finite number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(',')}]`;
  if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(',')}}`;
  }
  throw new Error('render recipe must contain only JSON values');
}

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

export function renderFingerprint(recipe) {
  return sha256(stableStringify(recipe));
}

export function expectedCacheIdentity({ source, fingerprint, backend }) {
  if (!SHA256.test(fingerprint)) throw new Error('render fingerprint must be lowercase hexadecimal');
  if (!['swiftshader', 'gpu'].includes(backend)) throw new Error(`invalid thumbnail backend: ${backend}`);
  return {
    'source-etag': normalizeEtag(source.etag),
    'source-size': String(source.size),
    'render-fingerprint': fingerprint,
    width: String(THUMBNAIL_SIZE),
    height: String(THUMBNAIL_SIZE),
    backend,
  };
}

export function expectedThumbnailMetadata({ source, sourceSha256, fingerprint, backend }) {
  if (!SHA256.test(sourceSha256)) throw new Error('source SHA-256 must be lowercase hexadecimal');
  return { ...expectedCacheIdentity({ source, fingerprint, backend }), 'source-sha256': sourceSha256 };
}

function normalizeMetadata(metadata) {
  const normalized = {};
  for (const [key, value] of Object.entries(metadata ?? {})) {
    if (typeof value !== 'string') return null;
    const normalizedKey = key.toLowerCase();
    if (Object.hasOwn(normalized, normalizedKey)) return null;
    normalized[normalizedKey] = value;
  }
  return normalized;
}

export function evaluateCacheMetadata(metadata, expectedBase) {
  const actual = normalizeMetadata(metadata);
  if (!actual) return { matches: false, reason: 'metadata contains a non-string or duplicate key' };
  const expectedKeys = [...new Set([...Object.keys(expectedBase), 'source-sha256', 'thumb-sha256'])].sort();
  const actualKeys = Object.keys(actual).sort();
  if (stableStringify(actualKeys) !== stableStringify(expectedKeys)) {
    return { matches: false, reason: `metadata keys differ: expected [${expectedKeys}], received [${actualKeys}]` };
  }
  for (const [key, value] of Object.entries(expectedBase)) {
    if (actual[key] !== value) return { matches: false, reason: `metadata ${key} differs` };
  }
  if (!SHA256.test(actual['source-sha256'])) return { matches: false, reason: 'metadata source-sha256 is invalid' };
  if (!SHA256.test(actual['thumb-sha256'])) return { matches: false, reason: 'metadata thumb-sha256 is invalid' };
  return {
    matches: true,
    sourceSha256: actual['source-sha256'],
    thumbSha256: actual['thumb-sha256'],
    metadata: actual,
  };
}

function bodyAsReadable(body) {
  if (body instanceof Uint8Array) return Readable.from([body]);
  if (body && typeof body[Symbol.asyncIterator] === 'function') return body;
  if (body && typeof body.getReader === 'function') return Readable.fromWeb(body);
  throw new Error('R2 GetObject response Body is not a readable byte stream');
}

async function streamBodyToFile(body, outputPath) {
  const digest = createHash('sha256');
  let size = 0;
  const tap = new Transform({
    transform(chunk, _encoding, callback) {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      digest.update(bytes);
      size += bytes.length;
      callback(null, bytes);
    },
  });
  await pipeline(bodyAsReadable(body), tap, createWriteStream(outputPath, { flags: 'w' }));
  return { size, sha256: digest.digest('hex') };
}

async function bodyToBuffer(body) {
  const chunks = [];
  let size = 0;
  for await (const chunk of bodyAsReadable(body)) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    chunks.push(bytes);
    size += bytes.length;
  }
  return Buffer.concat(chunks, size);
}

async function downloadSource(client, bucket, source, outputPath) {
  const response = await client.send(
    new GetObjectCommand({ Bucket: bucket, Key: source.key, IfMatch: source.ifMatch }),
  );
  if (normalizeEtag(response.ETag) !== source.etag) throw new Error(`source ETag changed during download: ${source.key}`);
  if (response.ContentLength !== source.size) throw new Error(`source ContentLength changed during download: ${source.key}`);
  if (!response.Body) throw new Error(`source GetObject response has no Body: ${source.key}`);
  const downloaded = await streamBodyToFile(response.Body, outputPath);
  if (downloaded.size !== source.size) {
    throw new Error(`source byte count differs: ${source.key} expected ${source.size}, received ${downloaded.size}`);
  }
  return downloaded;
}

async function verifySourceStillCurrent(client, bucket, source) {
  let response;
  try {
    response = await client.send(
      new HeadObjectCommand({ Bucket: bucket, Key: source.key, IfMatch: source.ifMatch }),
    );
  } catch (error) {
    throw new Error(`source changed while thumbnail was being published: ${source.key}`, { cause: error });
  }
  if (normalizeEtag(response.ETag) !== source.etag || response.ContentLength !== source.size) {
    throw new Error(`source identity changed while thumbnail was being published: ${source.key}`);
  }
}

export async function validateThumbnailBuffer(buffer) {
  const metadata = await sharp(buffer, { failOn: 'error' }).metadata();
  if (metadata.format !== 'webp') throw new Error(`thumbnail must be WebP, received ${metadata.format ?? 'unknown'}`);
  if (metadata.width !== THUMBNAIL_SIZE || metadata.height !== THUMBNAIL_SIZE) {
    throw new Error(
      `thumbnail must be ${THUMBNAIL_SIZE}x${THUMBNAIL_SIZE}, received ${metadata.width ?? '?'}x${metadata.height ?? '?'}`,
    );
  }
  if ((metadata.pages ?? 1) !== 1) throw new Error('thumbnail must be a static WebP image');
  const { data, info } = await sharp(buffer, { failOn: 'error' }).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  if (info.channels !== 4) throw new Error(`decoded thumbnail must have four channels, received ${info.channels}`);
  let hasVisiblePixel = false;
  for (let index = 3; index < data.length; index += 4) {
    if (data[index] !== 0) {
      hasVisiblePixel = true;
      break;
    }
  }
  if (!hasVisiblePixel) throw new Error('thumbnail must not be fully transparent');
  return { width: metadata.width, height: metadata.height, size: buffer.length, sha256: sha256(buffer) };
}

function isMissingObject(error) {
  return (
    error?.$metadata?.httpStatusCode === 404 ||
    error?.name === 'NotFound' ||
    error?.name === 'NoSuchKey' ||
    error?.Code === 'NoSuchKey'
  );
}

async function inspectRemoteThumbnail(client, { bucket, key, expectedBase }) {
  let head;
  try {
    head = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
  } catch (error) {
    if (isMissingObject(error)) return { fresh: false, reason: 'thumbnail object is missing' };
    throw error;
  }
  const etag = normalizeEtag(head.ETag);
  const stale = (reason) => ({ fresh: false, reason, etag });
  if (head.ContentType !== 'image/webp') return stale('thumbnail Content-Type differs');
  if (head.CacheControl !== THUMBNAIL_CACHE_CONTROL) {
    return stale('thumbnail Cache-Control differs');
  }
  if (!Number.isSafeInteger(head.ContentLength) || head.ContentLength <= 0) {
    return stale('thumbnail Content-Length is invalid');
  }
  const metadataCheck = evaluateCacheMetadata(head.Metadata, expectedBase);
  if (!metadataCheck.matches) return stale(metadataCheck.reason);

  const response = await client.send(
    new GetObjectCommand({ Bucket: bucket, Key: key, IfMatch: formatIfMatch(etag) }),
  );
  if (normalizeEtag(response.ETag) !== etag) return stale('thumbnail ETag changed during download');
  if (response.ContentType !== 'image/webp') return stale('thumbnail GET Content-Type differs');
  if (response.CacheControl !== THUMBNAIL_CACHE_CONTROL) {
    return stale('thumbnail GET Cache-Control differs');
  }
  if (response.ContentLength !== head.ContentLength) return stale('thumbnail size changed during download');
  const getMetadataCheck = evaluateCacheMetadata(response.Metadata, expectedBase);
  if (!getMetadataCheck.matches || getMetadataCheck.thumbSha256 !== metadataCheck.thumbSha256) {
    return stale('thumbnail GET metadata differs from HEAD metadata');
  }
  if (!response.Body) return stale('thumbnail GetObject response has no Body');
  const buffer = await bodyToBuffer(response.Body);
  if (buffer.length !== head.ContentLength) return stale('thumbnail downloaded byte count differs');
  let inspection;
  try {
    inspection = await validateThumbnailBuffer(buffer);
  } catch (error) {
    return stale(`thumbnail decode validation failed: ${error.message}`);
  }
  if (inspection.sha256 !== metadataCheck.thumbSha256) {
    return stale('thumbnail SHA-256 differs from metadata');
  }
  return { fresh: true, etag, sourceSha256: metadataCheck.sourceSha256, ...inspection };
}

async function encodeWebp(pngPath, webpOptions) {
  const pngBuffer = await readFile(pngPath);
  const input = await sharp(pngBuffer, { failOn: 'error' }).metadata();
  if (input.format !== 'png' || input.width !== THUMBNAIL_SIZE || input.height !== THUMBNAIL_SIZE) {
    throw new Error(
      `renderer output must be ${THUMBNAIL_SIZE}x${THUMBNAIL_SIZE} PNG, received ` +
        `${input.format ?? 'unknown'} ${input.width ?? '?'}x${input.height ?? '?'}`,
    );
  }
  if ((input.pages ?? 1) !== 1) throw new Error('renderer output must be a static PNG');
  const buffer = await sharp(pngBuffer, { failOn: 'error' }).webp(webpOptions).toBuffer();
  return { buffer, ...(await validateThumbnailBuffer(buffer)) };
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

async function clearCellTemporaries(paths) {
  await Promise.all(paths.map((item) => unlink(item).catch((error) => {
    if (error?.code !== 'ENOENT') throw error;
  })));
}

export async function runThumbnailBatch({
  client,
  bucket,
  prefix,
  modelIds,
  taskIds,
  expectedFailures,
  model = null,
  task = null,
  backend,
  check,
  force,
  rendererRecipe,
  webpOptions,
  createRenderer,
  report,
  temporaryParent = tmpdir(),
  onProgress = () => {},
}) {
  const fingerprint = renderFingerprint(rendererRecipe);
  report.renderFingerprint = fingerprint;
  report.inventory = null;
  report.cells = [];
  const objects = await listSiteDataObjects(client, { bucket, prefix });
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
  onProgress(
    `inventory: ${inventory.successCells.length} success, ${inventory.failureCells.length} expected failure; ` +
      `${selected.length} selected`,
  );

  const temporaryDirectory = await mkdtemp(path.join(temporaryParent, '3dgen-thumbnails-'));
  const glbPath = path.join(temporaryDirectory, 'source.glb');
  const pngPath = path.join(temporaryDirectory, 'render.png');
  let renderer = null;
  let operationError = null;

  try {
    for (const cell of selected) {
      onProgress(`${cell.modelId}/${cell.taskId}: inspect`);
      const cellReport = {
        modelId: cell.modelId,
        taskId: cell.taskId,
        source: { key: cell.source.key, etag: cell.source.etag, size: cell.source.size },
        status: 'running',
      };
      report.cells.push(cellReport);
      try {
        await clearCellTemporaries([glbPath, pngPath]);
        const expectedIdentity = expectedCacheIdentity({
          source: cell.source,
          fingerprint,
          backend,
        });

        const cached = await inspectRemoteThumbnail(client, {
          bucket,
          key: cell.thumbnailKey,
          expectedBase: expectedIdentity,
        });
        if (!force) {
          if (cached.fresh) {
            cellReport.status = 'fresh';
            cellReport.source.sha256 = cached.sourceSha256;
            cellReport.thumbnail = { key: cell.thumbnailKey, etag: cached.etag, size: cached.size, sha256: cached.sha256 };
            onProgress(`${cell.modelId}/${cell.taskId}: fresh`);
            continue;
          }
          cellReport.cacheReason = cached.reason;
          if (check) {
            cellReport.status = 'stale';
            throw new Error(`thumbnail cache is not fresh: ${cached.reason}`);
          }
        } else {
          cellReport.cacheReason = 'forced regeneration';
        }

        if (check) throw new Error('internal error: check mode reached thumbnail rendering');
        const sourceDownload = await downloadSource(client, bucket, cell.source, glbPath);
        cellReport.source.sha256 = sourceDownload.sha256;
        const expectedBase = {
          ...expectedIdentity,
          'source-sha256': sourceDownload.sha256,
        };
        if (!renderer) {
          if (typeof createRenderer !== 'function') throw new Error('thumbnail renderer factory is required');
          renderer = await createRenderer({ backend });
          if (stableStringify(renderer.recipe) !== stableStringify(rendererRecipe)) {
            throw new Error('thumbnail renderer recipe differs from the fingerprinted recipe');
          }
        }
        const renderResult = await renderer.render({
          glbPath,
          outputPath: pngPath,
          modelId: cell.modelId,
          taskId: cell.taskId,
        });
        if (renderResult?.width !== THUMBNAIL_SIZE || renderResult?.height !== THUMBNAIL_SIZE) {
          throw new Error('thumbnail renderer returned unexpected output dimensions');
        }
        const encoded = await encodeWebp(pngPath, webpOptions);
        const uploadMetadata = { ...expectedBase, 'thumb-sha256': encoded.sha256 };
        await verifySourceStillCurrent(client, bucket, cell.source);
        await client.send(
          new PutObjectCommand({
            Bucket: bucket,
            Key: cell.thumbnailKey,
            Body: encoded.buffer,
            ContentLength: encoded.size,
            ContentType: 'image/webp',
            CacheControl: THUMBNAIL_CACHE_CONTROL,
            Metadata: uploadMetadata,
            ...thumbnailWriteCondition(cached.etag),
          }),
        );
        const published = await inspectRemoteThumbnail(client, {
          bucket,
          key: cell.thumbnailKey,
          expectedBase,
        });
        if (!published.fresh || published.sha256 !== encoded.sha256) {
          throw new Error(`published thumbnail verification failed: ${published.reason ?? 'SHA-256 differs'}`);
        }
        await verifySourceStillCurrent(client, bucket, cell.source);
        cellReport.status = 'rendered';
        cellReport.thumbnail = {
          key: cell.thumbnailKey,
          etag: published.etag,
          size: published.size,
          sha256: published.sha256,
        };
        cellReport.renderer = {
          webglRenderer: renderResult.webglRenderer,
          stats: renderResult.stats,
        };
        onProgress(`${cell.modelId}/${cell.taskId}: rendered (${encoded.size} bytes)`);
      } catch (error) {
        if (cellReport.status === 'running') cellReport.status = 'failed';
        cellReport.error = errorMessage(error);
        onProgress(`${cell.modelId}/${cell.taskId}: failed: ${cellReport.error}`);
        throw new Error(`${cell.modelId}/${cell.taskId}: ${errorMessage(error)}`, { cause: error });
      }
    }
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
      if (operationError) throw new AggregateError([operationError, ...cleanupErrors], 'thumbnail batch and cleanup failed');
      throw new AggregateError(cleanupErrors, 'thumbnail batch cleanup failed');
    }
  }

  return report;
}
