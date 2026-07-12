import { mkdir, mkdtemp, rename, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { chromium } from 'playwright';
import sharp from 'sharp';

export const DEFAULT_BASE_URL = 'https://3dgen.hitsuki.space/';
export const TASK_ID = 'scifi-supply-crate';
export const VIEWPORT = Object.freeze({ width: 1600, height: 900 });
export const DEVICE_SCALE_FACTOR = 2;
export const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

const scriptPath = fileURLToPath(import.meta.url);
const webRoot = path.resolve(path.dirname(scriptPath), '..');
const outputDir = path.resolve(webRoot, '..', 'docs', 'images');
const statsPattern = /^\d[\d,]* tris \/ \d[\d,]* verts$/;

function normalizeBaseUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`--base-url must be an absolute HTTP(S) URL, received: ${value}`);
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error(`--base-url must be an unauthenticated HTTP(S) URL, received: ${value}`);
  }
  if (url.search || url.hash) {
    throw new Error('--base-url must not contain a query string or fragment');
  }
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url.href;
}

export function parseArgs(argv) {
  let baseUrl = DEFAULT_BASE_URL;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg !== '--base-url') throw new Error(`unknown argument: ${arg}`);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error('--base-url requires a value');
    baseUrl = normalizeBaseUrl(value);
    index += 1;
  }
  return { baseUrl };
}

async function waitForFontsAndImages(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    const images = [...document.images].filter((image) => {
      const rect = image.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight;
    });
    await Promise.all(
      images.map((image) =>
        image.complete
          ? Promise.resolve()
          : new Promise((resolve, reject) => {
              image.addEventListener('load', resolve, { once: true });
              image.addEventListener('error', () => reject(new Error(`image failed: ${image.currentSrc}`)), {
                once: true,
              });
            }),
      ),
    );
  });
}

async function waitForRenderedFrames(page) {
  await page.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
}

async function assertWebGlHealthy(page) {
  const state = await page.locator('#viewer-canvas').evaluate((canvas) => {
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    return { width: canvas.width, height: canvas.height, contextLost: context?.isContextLost() ?? true };
  });
  if (state.width === 0 || state.height === 0 || state.contextLost) {
    throw new Error(`viewer canvas is not healthy: ${JSON.stringify(state)}`);
  }
}

async function waitForVisiblePaneStats(page, requiredTitles) {
  await page.waitForFunction(
    ({ source, titles }) => {
      const pattern = new RegExp(source);
      const paneRoots = [...document.querySelectorAll('a[title^="GLB "]')]
        .map((link) => {
          let current = link.parentElement;
          while (current) {
            if (
              current.classList.contains('flex') &&
              current.classList.contains('flex-col') &&
              current.classList.contains('rounded-lg') &&
              current.classList.contains('overflow-hidden')
            ) {
              return current;
            }
            current = current.parentElement;
          }
          return null;
        })
        .filter((pane, index, panes) => pane && panes.indexOf(pane) === index);
      const fullyVisible = paneRoots.filter((pane) => {
        const rect = pane.getBoundingClientRect();
        return rect.top >= 0 && rect.bottom <= window.innerHeight;
      });
      const hasStats = (pane) =>
        [...pane.querySelectorAll('span')].some((span) => pattern.test(span.textContent?.trim() ?? ''));
      const titleOf = (pane) => pane.firstElementChild?.querySelector('span')?.textContent?.trim();
      return (
        fullyVisible.length >= titles.length &&
        fullyVisible.every(hasStats) &&
        titles.every((title) => fullyVisible.some((pane) => titleOf(pane) === title))
      );
    },
    { source: statsPattern.source, titles: requiredTitles },
    { timeout: 120_000 },
  );
}

function assertNoPageErrors(errors) {
  if (errors.length > 0) throw new Error(`page errors:\n${errors.join('\n')}`);
}

async function capturePng(page, destinationDir, filename, errors) {
  assertNoPageErrors(errors);
  const screenshot = await page.screenshot({
    type: 'png',
    animations: 'disabled',
    scale: 'device',
  });
  assertNoPageErrors(errors);
  const destination = path.join(destinationDir, filename);
  await sharp(screenshot)
    .png({ compressionLevel: 9, palette: true, quality: 95, effort: 10 })
    .toFile(destination);

  const metadata = await sharp(destination).metadata();
  const file = await stat(destination);
  const expectedWidth = VIEWPORT.width * DEVICE_SCALE_FACTOR;
  const expectedHeight = VIEWPORT.height * DEVICE_SCALE_FACTOR;
  if (metadata.width !== expectedWidth || metadata.height !== expectedHeight) {
    throw new Error(
      `${filename} must be ${expectedWidth}x${expectedHeight}, received ${metadata.width}x${metadata.height}`,
    );
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new Error(`${filename} exceeds 2 MiB: ${file.size} bytes`);
  }
  console.log(`${filename}: ${metadata.width}x${metadata.height}, ${file.size} bytes`);
}

async function run() {
  const { baseUrl } = parseArgs(process.argv.slice(2));
  await mkdir(outputDir, { recursive: true });
  const captureDir = await mkdtemp(path.join(outputDir, '.capture-'));
  console.log(`capturing ${baseUrl}`);

  // Headless Chromium + ANGLE SwiftShader keeps WebGL captures reproducible on CI and machines
  // without a configured display/GPU. The script still verifies a live, non-lost WebGL context.
  const browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=swiftshader'],
  });
  const errors = [];
  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: DEVICE_SCALE_FACTOR,
      colorScheme: 'dark',
      locale: 'ja-JP',
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();
    page.setDefaultTimeout(120_000);
    page.on('pageerror', (error) => errors.push(error.message));

    const response = await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
    if (!response?.ok()) throw new Error(`gallery navigation failed: HTTP ${response?.status() ?? 'none'}`);
    await page.getByRole('heading', { name: '3DGen DemoRoom', exact: true }).waitFor();
    await page.getByText('モデル 11/11 実測済み', { exact: true }).waitFor();
    await page.evaluate(() => window.scrollTo(0, 0));
    await waitForFontsAndImages(page);
    await waitForRenderedFrames(page);
    await capturePng(page, captureDir, 'gallery.png', errors);

    const taskUrl = new URL(baseUrl);
    taskUrl.hash = `t=${TASK_ID}`;
    await page.goto(taskUrl.href, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(taskUrl.href);
    const outputHeading = page.getByRole('heading', { name: /モデル別出力\(11\/11 完了\)/ });
    await outputHeading.waitFor();
    await outputHeading.scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -16));
    const requiredPanes = ['Stable Fast 3D', 'TripoSR', 'TRELLIS'];
    await waitForVisiblePaneStats(page, requiredPanes);
    await waitForFontsAndImages(page);
    await assertWebGlHealthy(page);
    await waitForRenderedFrames(page);
    await capturePng(page, captureDir, 'task-detail.png', errors);

    const wireframe = page.getByRole('button', { name: 'Wireframe', exact: true });
    await wireframe.click();
    await page.waitForFunction(
      (element) => element instanceof HTMLElement && element.classList.contains('bg-sky-700'),
      await wireframe.elementHandle(),
    );
    await waitForVisiblePaneStats(page, requiredPanes);
    await assertWebGlHealthy(page);
    await waitForRenderedFrames(page);
    await capturePng(page, captureDir, 'viewer-wireframe.png', errors);

    assertNoPageErrors(errors);
    for (const filename of ['gallery.png', 'task-detail.png', 'viewer-wireframe.png']) {
      const destination = path.join(outputDir, filename);
      await rm(destination, { force: true });
      await rename(path.join(captureDir, filename), destination);
    }
    await context.close();
  } finally {
    await browser.close();
    await rm(captureDir, { recursive: true, force: true });
  }
}

const isMain = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (isMain) {
  run().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
