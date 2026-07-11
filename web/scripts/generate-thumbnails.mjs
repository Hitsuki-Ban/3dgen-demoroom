import { readFile, mkdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { S3Client } from '@aws-sdk/client-s3';

import {
  parseCliArgs,
  parseModelRegistry,
  parseTasks,
  requireR2Environment,
  runThumbnailBatch,
} from './thumbnail-batch-lib.mjs';
import { createThumbnailRenderer, thumbnailRecipe } from './thumbnail-renderer.mjs';

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const modelRegistryPath = path.join(webRoot, 'src', 'data', 'model-registry.json');
const tasksPath = path.resolve(webRoot, '..', 'tasks', 'tasks.json');

function safeError(error) {
  return {
    name: error instanceof Error ? error.name : 'Error',
    message: error instanceof Error ? error.message : String(error),
  };
}

function summarize(cells) {
  const summary = { selected: cells.length, fresh: 0, rendered: 0, stale: 0, failed: 0 };
  for (const cell of cells) {
    if (Object.hasOwn(summary, cell.status)) summary[cell.status] += 1;
  }
  return summary;
}

async function writeReportFile(reportPath, reportText) {
  const absolutePath = path.resolve(reportPath);
  await mkdir(path.dirname(absolutePath), { recursive: true });
  const temporaryPath = `${absolutePath}.tmp-${process.pid}`;
  try {
    await writeFile(temporaryPath, reportText, { encoding: 'utf8', flag: 'wx' });
    await rm(absolutePath, { force: true });
    await rename(temporaryPath, absolutePath);
  } finally {
    await rm(temporaryPath, { force: true });
  }
}

export async function main(argv = process.argv.slice(2), environment = process.env) {
  const report = {
    schemaVersion: 1,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    ok: false,
    mode: null,
    backend: null,
    source: null,
    selection: null,
    expectedFailures: null,
    inventory: null,
    renderFingerprint: null,
    recipe: null,
    cells: [],
    summary: null,
    error: null,
  };
  let args = null;
  let exitCode = 0;

  try {
    args = parseCliArgs(argv);
    const r2 = requireR2Environment(environment);
    const [modelPayload, taskPayload] = await Promise.all([
      readFile(modelRegistryPath, 'utf8').then(JSON.parse),
      readFile(tasksPath, 'utf8').then(JSON.parse),
    ]);
    const modelIds = parseModelRegistry(modelPayload);
    const taskIds = parseTasks(taskPayload);
    const rendererRecipe = Object.freeze({ ...thumbnailRecipe, backend: args.backend });
    const client = new S3Client({
      region: 'auto',
      endpoint: r2.endpoint,
      credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
      maxAttempts: 1,
    });

    report.mode = args.check ? 'check' : args.force ? 'force' : 'update';
    report.backend = args.backend;
    report.source = args.s3Root;
    report.selection = { model: args.model, task: args.task };
    report.expectedFailures = [...args.expectedFailures].sort();
    report.recipe = rendererRecipe;
    await runThumbnailBatch({
      client,
      ...args.s3Root,
      modelIds,
      taskIds,
      expectedFailures: args.expectedFailures,
      model: args.model,
      task: args.task,
      backend: args.backend,
      check: args.check,
      force: args.force,
      rendererRecipe,
      webpOptions: thumbnailRecipe.webp,
      createRenderer: createThumbnailRenderer,
      report,
      onProgress: (message) => process.stderr.write(`[thumbnail] ${message}\n`),
    });
    report.ok = true;
  } catch (error) {
    report.error = safeError(error);
    exitCode = 1;
  } finally {
    report.finishedAt = new Date().toISOString();
    report.summary = summarize(report.cells);
    let reportText = `${JSON.stringify(report, null, 2)}\n`;
    if (args?.report) {
      try {
        await writeReportFile(args.report, reportText);
      } catch (error) {
        report.ok = false;
        report.error = report.error
          ? {
              name: 'AggregateError',
              message: `${report.error.message}; report write failed: ${safeError(error).message}`,
            }
          : { name: 'Error', message: `report write failed: ${safeError(error).message}` };
        exitCode = 1;
        reportText = `${JSON.stringify(report, null, 2)}\n`;
      }
    }
    process.stdout.write(reportText);
  }
  return exitCode;
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) {
  process.exitCode = await main();
}
