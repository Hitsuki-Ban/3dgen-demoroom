import type { Object3D } from 'three';

/** jsdom には WebGL が無いため、テストでは ViewerCore を API 互換のスタブに差し替える。
 *  使い方: vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'))
 *  (相対パスはテストファイル位置に合わせる) */
export type DisplayMode = 'pbr' | 'toon' | 'matcap' | 'wireframe' | 'normal' | 'uv';

export interface PaneStats {
  triangles: number;
  vertices: number;
}

export class ViewerCore {
  static instances: ViewerCore[] = [];
  disposed = false;
  paneCount = 0;

  private mode: DisplayMode = 'pbr';
  private cameraSync = true;
  private orientationFixEnabled = true;
  private listeners = new Set<() => void>();

  constructor(_canvas: HTMLCanvasElement) {
    ViewerCore.instances.push(this);
  }

  /** テストから addPane に渡された orientationFix を検証できるよう記録する */
  addPaneCalls: Array<{ fix?: { x?: number; y?: number; z?: number } }> = [];

  addPane(_el: HTMLElement, _object: Object3D, fix?: { x?: number; y?: number; z?: number }): number {
    this.addPaneCalls.push({ fix });
    this.paneCount += 1;
    return this.paneCount;
  }
  removePane(_id: number): void {}
  getStats(_id: number): PaneStats {
    return { triangles: 0, vertices: 0 };
  }
  setDisplayMode(m: DisplayMode): void {
    this.mode = m;
    this.emit();
  }
  getDisplayMode(): DisplayMode {
    return this.mode;
  }
  setCameraSync(v: boolean): void {
    this.cameraSync = v;
    this.emit();
  }
  getCameraSync(): boolean {
    return this.cameraSync;
  }
  setOrientationFixEnabled(v: boolean): void {
    this.orientationFixEnabled = v;
    this.emit();
  }
  getOrientationFixEnabled(): boolean {
    return this.orientationFixEnabled;
  }
  subscribeChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  resetCameras(): void {}
  dispose(): void {
    this.disposed = true;
  }

  private emit(): void {
    for (const l of this.listeners) l();
  }
}
