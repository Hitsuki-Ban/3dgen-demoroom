import { MODELS } from './data/models';
import { ViewerCore } from './viewer/ViewerCore';
import { loadModel } from './viewer/loadModel';

type ThumbnailState =
  | { status: 'loading' }
  | {
      status: 'ready';
      modelId: string;
      meshes: number;
      triangles: number;
      vertices: number;
      webglRenderer: string;
    }
  | { status: 'error'; message: string };

type OrientationDegrees = { x: number; y: number; z: number };

interface ThumbnailControl {
  setOrientationDegrees(orientation: OrientationDegrees): Promise<void>;
}

declare global {
  interface Window {
    __THUMBNAIL_STATE__: ThumbnailState;
    __THUMBNAIL_CONTROL__?: ThumbnailControl;
  }
}

window.__THUMBNAIL_STATE__ = { status: 'loading' };

function requiredElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`missing thumbnail renderer element: ${selector}`);
  return element;
}

function defaultOrientation(modelId: string): OrientationDegrees {
  const model = MODELS.find((candidate) => candidate.id === modelId);
  if (!model) throw new Error(`unknown model ID: ${modelId}`);
  const fix = model.orientationFix;
  return { x: fix?.x ?? 0, y: fix?.y ?? 0, z: fix?.z ?? 0 };
}

function animationFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

async function renderThumbnail(): Promise<void> {
  const modelId = new URLSearchParams(window.location.search).get('model');
  if (!modelId) throw new Error('model query parameter is required');

  const canvas = requiredElement<HTMLCanvasElement>('#thumbnail-canvas');
  const pane = requiredElement<HTMLDivElement>('#thumbnail-pane');
  if (pane.clientWidth !== 320 || pane.clientHeight !== 320) {
    throw new Error(`thumbnail pane must be 320x320, received ${pane.clientWidth}x${pane.clientHeight}`);
  }

  const core = new ViewerCore(canvas);
  const object = await loadModel(`/__thumbnail/model.glb?token=${encodeURIComponent(window.location.search)}`);
  const paneId = core.addPane(pane, object);

  window.__THUMBNAIL_CONTROL__ = {
    async setOrientationDegrees(orientation) {
      core.setPaneOrientationDegrees(paneId, orientation);
      await animationFrame();
      await animationFrame();
    },
  };

  // ViewerCore registers its render-loop callback before these callbacks. Two
  // observed animation frames therefore guarantee at least one completed pane
  // render without relying on a wall-clock sleep.
  await window.__THUMBNAIL_CONTROL__.setOrientationDegrees(defaultOrientation(modelId));

  const stats = core.getStats(paneId);
  const context = core.renderer.getContext();
  const debugInfo = context.getExtension('WEBGL_debug_renderer_info');
  const webglRenderer = debugInfo
    ? String(context.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL))
    : String(context.getParameter(context.RENDERER));
  window.__THUMBNAIL_STATE__ = {
    status: 'ready',
    modelId,
    meshes: stats.meshes,
    triangles: stats.triangles,
    vertices: stats.vertices,
    webglRenderer,
  };
}

renderThumbnail().catch((error: unknown) => {
  window.__THUMBNAIL_STATE__ = {
    status: 'error',
    message: error instanceof Error ? error.stack ?? error.message : String(error),
  };
});
