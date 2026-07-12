import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { S3Client } from '@aws-sdk/client-s3';

import {
  parseModelRegistry,
  parseTasks,
  requireR2Environment,
} from './thumbnail-batch-lib.mjs';
import {
  parseOrientationSearchArgs,
  runOrientationSearch,
  writeJsonAtomic,
} from './orientation-search-lib.mjs';
import { createThumbnailRenderer } from './thumbnail-renderer.mjs';

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const modelRegistryPath = path.join(webRoot, 'src', 'data', 'model-registry.json');
const tasksPath = path.resolve(webRoot, '..', 'tasks', 'tasks.json');

function safeError(error) {
  return { name: error instanceof Error ? error.name : 'Error', message: error instanceof Error ? error.message : String(error) };
}

function summarize(cells) {
  const summary = { selected: cells.length, ranked: 0, failed: 0 };
  for (const cell of cells) {
    if (cell.status === 'ranked') summary.ranked += 1;
    else if (cell.status === 'failed') summary.failed += 1;
  }
  return summary;
}

export async function main(argv = process.argv.slice(2), environment = process.env) {
  let args;
  try {
    args = parseOrientationSearchArgs(argv);
  } catch (error) {
    process.stderr.write(`${safeError(error).message}\n`);
    return 1;
  }

  const report = {
    schemaVersion: 1,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    ok: false,
    backend: args.backend,
    source: args.r2RootValue,
    output: path.resolve(args.output),
    referenceMaskRoot: path.resolve(args.referenceMaskRoot),
    selection: { model: args.model, task: args.task },
    reviewAllCandidates: args.reviewAllCandidates,
    expectedFailures: [...args.expectedFailures].sort(),
    recipe: null,
    inventory: null,
    cells: [],
    errors: [],
    summary: null,
    error: null,
  };
  let exitCode = 0;
  try {
    const r2 = requireR2Environment(environment);
    const [modelPayload, taskPayload] = await Promise.all([
      readFile(modelRegistryPath, 'utf8').then(JSON.parse),
      readFile(tasksPath, 'utf8').then(JSON.parse),
    ]);
    const modelIds = parseModelRegistry(modelPayload);
    const taskIds = parseTasks(taskPayload);
    if (modelIds.length !== 11 || taskIds.length !== 25 || args.expectedFailures.size !== 1) {
      throw new Error(
        `orientation search requires the canonical 11x25 inventory and exactly one expected failure; received ` +
          `${modelIds.length} models, ${taskIds.length} tasks, ${args.expectedFailures.size} expected failures`,
      );
    }
    const client = new S3Client({
      region: 'auto',
      endpoint: r2.endpoint,
      credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
      maxAttempts: 1,
    });
    await runOrientationSearch({
      client,
      ...args.r2Root,
      modelIds,
      taskIds,
      expectedFailures: args.expectedFailures,
      model: args.model,
      task: args.task,
      backend: args.backend,
      outputRoot: args.output,
      referenceMaskRoot: args.referenceMaskRoot,
      reviewAllCandidates: args.reviewAllCandidates,
      createRenderer: createThumbnailRenderer,
      report,
      onProgress: (message) => process.stderr.write(`[orientation] ${message}\n`),
    });
    report.ok = true;
  } catch (error) {
    report.error = safeError(error);
    exitCode = 1;
  } finally {
    report.finishedAt = new Date().toISOString();
    report.summary = summarize(report.cells);
    try {
      await writeJsonAtomic(args.report, report);
    } catch (error) {
      report.ok = false;
      report.error = report.error
        ? { name: 'AggregateError', message: `${report.error.message}; report write failed: ${safeError(error).message}` }
        : { name: 'Error', message: `report write failed: ${safeError(error).message}` };
      exitCode = 1;
    }
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  }
  return exitCode;
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) {
  process.exitCode = await main();
}
