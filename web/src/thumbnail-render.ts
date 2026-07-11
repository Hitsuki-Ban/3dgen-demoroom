import * as THREE from 'three';
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

declare global {
  interface Window {
    __THUMBNAIL_STATE__: ThumbnailState;
  }
}

window.__THUMBNAIL_STATE__ = { status: 'loading' };

function requiredElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`missing thumbnail renderer element: ${selector}`);
  return element;
}

function applyDefaultOrientation(object: THREE.Object3D, modelId: string): void {
  const model = MODELS.find((candidate) => candidate.id === modelId);
  if (!model) throw new Error(`unknown model ID: ${modelId}`);
  const fix = model.orientationFix;
  if (!fix) return;
  const degrees = Math.PI / 180;
  object.rotation.set((fix.x ?? 0) * degrees, (fix.y ?? 0) * degrees, (fix.z ?? 0) * degrees);
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
  applyDefaultOrientation(object, modelId);
  const paneId = core.addPane(pane, object);

  // ViewerCore registers its render-loop callback before these callbacks. Two
  // observed animation frames therefore guarantee at least one completed pane
  // render without relying on a wall-clock sleep.
  await animationFrame();
  await animationFrame();

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
