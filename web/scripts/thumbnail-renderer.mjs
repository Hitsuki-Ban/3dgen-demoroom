import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, readFile, rm, stat } from 'node:fs/promises';
import { createServer as createHttpServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { chromium } from 'playwright';
import sharp from 'sharp';
import { createServer as createViteServer } from 'vite';

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const require = createRequire(import.meta.url);
const packageJson = JSON.parse(await readFile(path.join(webRoot, 'package.json'), 'utf8'));

function exactVersion(section, name) {
  const version = packageJson[section]?.[name];
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error(`${name} must be pinned to an exact version in package.json`);
  }
  return version;
}

const playwrightPackagePath = require.resolve('playwright/package.json');
const playwrightRequire = createRequire(playwrightPackagePath);
const playwrightCorePackagePath = playwrightRequire.resolve('playwright-core/package.json');
const playwrightBrowsers = JSON.parse(
  await readFile(path.join(path.dirname(playwrightCorePackagePath), 'browsers.json'), 'utf8'),
);
const chromiumDescriptor = playwrightBrowsers.browsers.find((browser) => browser.name === 'chromium');
if (!chromiumDescriptor?.browserVersion || !chromiumDescriptor.revision) {
  throw new Error('Playwright Chromium descriptor is missing browserVersion or revision');
}

const recipeSources = [
  'thumbnail-render.html',
  'src/thumbnail-render.ts',
  'src/viewer/ViewerCore.ts',
  'src/viewer/loadModel.ts',
  'src/data/models.ts',
];

async function readRecipeSourceHashes() {
  return Object.fromEntries(
    await Promise.all(
      recipeSources.map(async (relativePath) => {
        const source = await readFile(path.join(webRoot, relativePath), 'utf8');
        return [
          relativePath,
          createHash('sha256').update(source.replace(/\r\n/g, '\n')).digest('hex'),
        ];
      }),
    ),
  );
}

const sourceHashes = await readRecipeSourceHashes();

async function assertRecipeSourcesUnchanged() {
  const current = await readRecipeSourceHashes();
  if (JSON.stringify(current) !== JSON.stringify(sourceHashes)) {
    throw new Error('thumbnail renderer source changed during the batch; restart with a new fingerprint');
  }
}

/**
 * Stable, serializable rendering recipe. The batch publisher includes this
 * object plus its explicit backend in the R2 cache fingerprint.
 */
export const thumbnailRecipe = Object.freeze({
  version: 1,
  width: 320,
  height: 320,
  deviceScaleFactor: 1,
  background: 'transparent',
  capture: {
    target: '#thumbnail-canvas',
    type: 'png',
    omitBackground: true,
    animations: 'disabled',
    scale: 'css',
  },
  backends: {
    swiftshader: { channel: 'headless-shell', args: ['--use-gl=angle', '--use-angle=swiftshader'] },
    gpu: { platform: 'win32', channel: 'chromium', args: ['--use-gl=angle', '--use-angle=d3d11'] },
  },
  camera: { position: [1.2, 0.9, 1.6], fov: 40, near: 0.01, far: 50 },
  framing: 'box3-center-max-dimension-unit-box',
  lighting: 'RoomEnvironment-PMREM',
  toneMapping: 'ACESFilmicToneMapping',
  webp: { quality: 85, alphaQuality: 100, effort: 6, smartSubsample: true },
  runtime: {
    three: exactVersion('dependencies', 'three'),
    playwright: exactVersion('devDependencies', 'playwright'),
    chromium: chromiumDescriptor.browserVersion,
    chromiumRevision: chromiumDescriptor.revision,
    sharp: exactVersion('devDependencies', 'sharp'),
    vite: exactVersion('devDependencies', 'vite'),
  },
  sourceHashes,
});

function launchOptions(backend) {
  if (backend === 'gpu') {
    if (process.platform !== 'win32') {
      throw new Error('the explicit gpu thumbnail backend currently requires Windows/ANGLE D3D11');
    }
    return {
      headless: true,
      channel: thumbnailRecipe.backends.gpu.channel,
      args: thumbnailRecipe.backends.gpu.args,
    };
  }
  if (backend === 'swiftshader') {
    return { headless: true, args: thumbnailRecipe.backends.swiftshader.args };
  }
  throw new Error(`thumbnail backend must be "swiftshader" or "gpu", received: ${backend}`);
}

function activeModelPlugin(state) {
  return {
    name: 'thumbnail-active-model',
    configureServer(server) {
      server.middlewares.use('/__thumbnail/model.glb', async (request, response, next) => {
        const pathname = (request.url ?? '').split('?', 1)[0];
        if (pathname !== '' && pathname !== '/') return next();
        const active = state.active;
        if (!active) {
          response.statusCode = 409;
          response.setHeader('Cache-Control', 'no-store');
          response.end('No thumbnail model is active');
          return;
        }
        try {
          response.statusCode = 200;
          response.setHeader('Content-Type', 'model/gltf-binary');
          response.setHeader('Content-Length', String(active.size));
          response.setHeader('Cache-Control', 'no-store');
          await pipeline(createReadStream(active.path), response);
        } catch (error) {
          if (!response.headersSent) next(error);
          else response.destroy(error instanceof Error ? error : new Error(String(error)));
        }
      });
    },
  };
}

export function assertWebglBackend(backend, webglRenderer) {
  if (typeof webglRenderer !== 'string' || !webglRenderer.trim()) {
    throw new Error('WebGL renderer identity is missing');
  }
  if (backend === 'swiftshader') {
    if (!/SwiftShader/i.test(webglRenderer)) {
      throw new Error(`swiftshader backend resolved to an unexpected WebGL renderer: ${webglRenderer}`);
    }
    return;
  }
  if (backend === 'gpu') {
    if (/SwiftShader|Basic Render Driver/i.test(webglRenderer) || !/Direct3D11|D3D11/i.test(webglRenderer)) {
      throw new Error(`gpu backend did not resolve to hardware ANGLE/D3D11: ${webglRenderer}`);
    }
    return;
  }
  throw new Error(`thumbnail backend must be "swiftshader" or "gpu", received: ${backend}`);
}

function listenOnEphemeralPort(server) {
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once('error', onError);
    server.listen(0, '127.0.0.1', () => {
      server.off('error', onError);
      resolve();
    });
  });
}

function closeHttpServer(server) {
  if (!server.listening) return Promise.resolve();
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function closeRendererResources(browser, httpServer, viteServer) {
  const results = await Promise.allSettled([
    browser ? browser.close() : Promise.resolve(),
    closeHttpServer(httpServer),
    viteServer.close(),
  ]);
  const errors = results.filter((result) => result.status === 'rejected').map((result) => result.reason);
  if (errors.length > 0) throw new AggregateError(errors, 'thumbnail renderer cleanup failed');
}

function serverBaseUrl(server) {
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Vite thumbnail server did not bind a TCP address');
  return `http://127.0.0.1:${address.port}`;
}

/** Start one Vite server and one pinned Chromium process for sequential renders. */
export async function createThumbnailRenderer({ backend = 'swiftshader', timeoutMs = 180_000 } = {}) {
  const browserLaunchOptions = launchOptions(backend);
  const state = { active: null };
  const viteServer = await createViteServer({
    root: webRoot,
    configFile: false,
    appType: 'mpa',
    logLevel: 'error',
    plugins: [activeModelPlugin(state)],
    server: { middlewareMode: true },
  });
  const httpServer = createHttpServer(viteServer.middlewares);

  let browser;
  try {
    await listenOnEphemeralPort(httpServer);
    try {
      browser = await chromium.launch(browserLaunchOptions);
    } catch (error) {
      throw new Error(
        `Pinned Chromium could not start. Run "pnpm exec playwright install chromium" in web/: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
    const browserVersion = browser.version();
    if (browserVersion !== thumbnailRecipe.runtime.chromium) {
      throw new Error(
        `Playwright Chromium version mismatch: expected ${thumbnailRecipe.runtime.chromium}, received ${browserVersion}`,
      );
    }
  } catch (error) {
    try {
      await closeRendererResources(browser, httpServer, viteServer);
    } catch (cleanupError) {
      throw new AggregateError([error, cleanupError], 'thumbnail renderer startup and cleanup failed');
    }
    throw error;
  }

  let renderSequence = 0;
  let closed = false;
  return {
    recipe: Object.freeze({ ...thumbnailRecipe, backend }),
    async render({ glbPath, outputPath, modelId, taskId }) {
      if (closed) throw new Error('thumbnail renderer is closed');
      if (!/^[a-z0-9-]+$/.test(modelId)) throw new Error(`invalid model ID: ${modelId}`);
      if (!/^[a-z0-9-]+$/.test(taskId)) throw new Error(`invalid task ID: ${taskId}`);
      await assertRecipeSourcesUnchanged();
      const sourceStats = await stat(glbPath);
      if (!sourceStats.isFile() || sourceStats.size === 0) throw new Error(`GLB is missing or empty: ${glbPath}`);
      await mkdir(path.dirname(outputPath), { recursive: true });

      renderSequence += 1;
      state.active = { path: path.resolve(glbPath), size: sourceStats.size };
      const page = await browser.newPage({
        viewport: { width: thumbnailRecipe.width, height: thumbnailRecipe.height },
        deviceScaleFactor: thumbnailRecipe.deviceScaleFactor,
      });
      page.setDefaultTimeout(timeoutMs);
      const pageErrors = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      try {
        const url = new URL('/thumbnail-render.html', serverBaseUrl(httpServer));
        url.searchParams.set('model', modelId);
        url.searchParams.set('task', taskId);
        url.searchParams.set('token', String(renderSequence));
        const response = await page.goto(url.href, { waitUntil: 'load', timeout: timeoutMs });
        if (!response?.ok()) throw new Error(`thumbnail render page returned HTTP ${response?.status() ?? 'none'}`);
        await page.waitForFunction(
          () => ['ready', 'error'].includes(window.__THUMBNAIL_STATE__?.status),
          undefined,
          { timeout: timeoutMs },
        );
        const result = await page.evaluate(() => window.__THUMBNAIL_STATE__);
        if (result.status === 'error') throw new Error(result.message);
        if (pageErrors.length > 0) throw new Error(`thumbnail page error: ${pageErrors.join('; ')}`);
        assertWebglBackend(backend, result.webglRenderer);

        await page.locator(thumbnailRecipe.capture.target).screenshot({
          path: outputPath,
          type: thumbnailRecipe.capture.type,
          omitBackground: thumbnailRecipe.capture.omitBackground,
          animations: thumbnailRecipe.capture.animations,
          scale: thumbnailRecipe.capture.scale,
        });
        await assertRecipeSourcesUnchanged();
        const screenshot = await readFile(outputPath);
        const metadata = await sharp(screenshot, { failOn: 'error' }).metadata();
        if (
          metadata.format !== 'png' ||
          metadata.width !== thumbnailRecipe.width ||
          metadata.height !== thumbnailRecipe.height
        ) {
          throw new Error(
            `thumbnail screenshot must be ${thumbnailRecipe.width}x${thumbnailRecipe.height} PNG, received ` +
              `${metadata.format ?? 'unknown'} ${metadata.width ?? '?'}x${metadata.height ?? '?'}`,
          );
        }
        return {
          width: metadata.width,
          height: metadata.height,
          webglRenderer: result.webglRenderer,
          stats: { meshes: result.meshes, triangles: result.triangles, vertices: result.vertices },
        };
      } finally {
        state.active = null;
        await page.close();
      }
    },
    async close() {
      if (closed) return;
      closed = true;
      state.active = null;
      await closeRendererResources(browser, httpServer, viteServer);
    },
  };
}

function parseLocalArguments(argv) {
  const parsed = { backend: 'swiftshader' };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--') continue;
    if (argument === '--backend') parsed.backend = argv[++index];
    else if (argument === '--input') parsed.input = argv[++index];
    else if (argument === '--output') parsed.output = argv[++index];
    else if (argument === '--model') parsed.modelId = argv[++index];
    else throw new Error(`unknown thumbnail renderer argument: ${argument}`);
  }
  for (const name of ['input', 'output', 'modelId']) {
    if (!parsed[name]) throw new Error(`--${name === 'modelId' ? 'model' : name} is required`);
  }
  if (path.extname(parsed.output).toLowerCase() !== '.webp') throw new Error('--output must end in .webp');
  return parsed;
}

async function localMain() {
  const args = parseLocalArguments(process.argv.slice(2));
  const tempPng = path.join(tmpdir(), `3dgen-thumb-${process.pid}-${Date.now()}.png`);
  const renderer = await createThumbnailRenderer({ backend: args.backend });
  try {
    const render = await renderer.render({
      glbPath: path.resolve(args.input),
      outputPath: tempPng,
      modelId: args.modelId,
      taskId: 'local-preview',
    });
    await mkdir(path.dirname(path.resolve(args.output)), { recursive: true });
    const screenshot = await readFile(tempPng);
    await sharp(screenshot, { failOn: 'error' }).webp(thumbnailRecipe.webp).toFile(path.resolve(args.output));
    process.stdout.write(`${path.resolve(args.output)}\nWebGL: ${render.webglRenderer}\n`);
  } finally {
    await renderer.close();
    await rm(tempPng, { force: true });
  }
}

if (pathToFileURL(process.argv[1] ?? '').href === import.meta.url) {
  localMain().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
