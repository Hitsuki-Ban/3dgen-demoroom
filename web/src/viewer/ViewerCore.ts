import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export type DisplayMode = 'pbr' | 'wireframe' | 'matcap' | 'normal' | 'uv';

export interface PaneStats {
  triangles: number;
  vertices: number;
  meshes: number;
}

interface Pane {
  id: number;
  element: HTMLElement;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  modelRoot: THREE.Group;
}

const CAMERA_HOME = new THREE.Vector3(1.2, 0.9, 1.6);

/**
 * 単一 WebGLRenderer + 単一 canvas で複数ペインを scissor viewport 描画するコア。
 * React には依存しない(React 側は薄いラッパーで mount する)。
 * 設計根拠: docs/research/viewer-hosting-merged.md
 */
export class ViewerCore {
  readonly renderer: THREE.WebGLRenderer;
  private panes = new Map<number, Pane>();
  private nextId = 1;
  private rafId = 0;
  private envMap: THREE.Texture;
  private mode: DisplayMode = 'pbr';
  private cameraSync = true;
  private syncing = false;
  private matcapTexture: THREE.Texture | null = null;
  private uvTexture: THREE.Texture | null = null;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setScissorTest(true);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.rafId = requestAnimationFrame(this.renderLoop);
  }

  dispose() {
    cancelAnimationFrame(this.rafId);
    for (const pane of [...this.panes.values()]) this.removePane(pane.id);
    this.renderer.dispose();
  }

  /** ペインを登録し、モデル(正規化済みで modelRoot に追加される)を表示する */
  addPane(element: HTMLElement, object: THREE.Object3D): number {
    const id = this.nextId++;
    const scene = new THREE.Scene();
    scene.environment = this.envMap;

    const modelRoot = new THREE.Group();
    normalizeIntoUnitBox(object);
    modelRoot.add(object);
    scene.add(modelRoot);

    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 50);
    camera.position.copy(CAMERA_HOME);

    const controls = new OrbitControls(camera, element);
    controls.enableDamping = true;
    controls.addEventListener('change', () => this.broadcastCamera(id));

    const pane: Pane = { id, element, scene, camera, controls, modelRoot };
    this.panes.set(id, pane);
    this.applyMode(pane, this.mode);
    return id;
  }

  removePane(id: number) {
    const pane = this.panes.get(id);
    if (!pane) return;
    pane.controls.dispose();
    pane.scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        disposeMaterial(o.material);
        const original = o.userData.originalMaterial as THREE.Material | undefined;
        if (original && original !== o.material) disposeMaterial(original);
      }
    });
    this.panes.delete(id);
  }

  getStats(id: number): PaneStats {
    const pane = this.panes.get(id);
    const stats: PaneStats = { triangles: 0, vertices: 0, meshes: 0 };
    pane?.modelRoot.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        stats.meshes += 1;
        const g = o.geometry as THREE.BufferGeometry;
        stats.vertices += g.attributes.position?.count ?? 0;
        const indexCount = g.index ? g.index.count : (g.attributes.position?.count ?? 0);
        stats.triangles += Math.floor(indexCount / 3);
      }
    });
    return stats;
  }

  setDisplayMode(mode: DisplayMode) {
    this.mode = mode;
    for (const pane of this.panes.values()) this.applyMode(pane, mode);
  }

  setCameraSync(enabled: boolean) {
    this.cameraSync = enabled;
    if (enabled && this.panes.size > 0) {
      const [first] = this.panes.values();
      this.broadcastCamera(first.id, true);
    }
  }

  resetCameras() {
    for (const pane of this.panes.values()) {
      pane.camera.position.copy(CAMERA_HOME);
      pane.controls.target.set(0, 0, 0);
      pane.controls.update();
    }
  }

  private broadcastCamera(sourceId: number, force = false) {
    if (this.syncing || (!this.cameraSync && !force)) return;
    const source = this.panes.get(sourceId);
    if (!source) return;
    this.syncing = true;
    for (const pane of this.panes.values()) {
      if (pane.id === sourceId) continue;
      pane.camera.position.copy(source.camera.position);
      pane.camera.quaternion.copy(source.camera.quaternion);
      pane.camera.zoom = source.camera.zoom;
      pane.camera.updateProjectionMatrix();
      pane.controls.target.copy(source.controls.target);
      pane.controls.update();
    }
    this.syncing = false;
  }

  private applyMode(pane: Pane, mode: DisplayMode) {
    pane.modelRoot.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      if (!o.userData.originalMaterial) o.userData.originalMaterial = o.material;
      const original = o.userData.originalMaterial as THREE.Material;
      switch (mode) {
        case 'pbr':
          o.material = original;
          break;
        case 'wireframe':
          o.material = new THREE.MeshBasicMaterial({ color: 0x7dd3fc, wireframe: true });
          break;
        case 'normal':
          o.material = new THREE.MeshNormalMaterial();
          break;
        case 'matcap':
          o.material = new THREE.MeshMatcapMaterial({ matcap: this.getMatcapTexture() });
          break;
        case 'uv':
          o.material = new THREE.MeshBasicMaterial({ map: this.getUvTexture() });
          break;
      }
    });
  }

  private getMatcapTexture(): THREE.Texture {
    if (!this.matcapTexture) {
      // クレイ調のシンプルな matcap を canvas で生成(外部アセット不要)
      const size = 256;
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext('2d')!;
      const g = ctx.createRadialGradient(size * 0.35, size * 0.3, size * 0.05, size * 0.5, size * 0.5, size * 0.7);
      g.addColorStop(0, '#f5f0ea');
      g.addColorStop(0.55, '#a89e92');
      g.addColorStop(1, '#3d3833');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size, size);
      this.matcapTexture = new THREE.CanvasTexture(canvas);
      this.matcapTexture.colorSpace = THREE.SRGBColorSpace;
    }
    return this.matcapTexture;
  }

  private getUvTexture(): THREE.Texture {
    if (!this.uvTexture) {
      const cells = 10;
      const cell = 64;
      const size = cells * cell;
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = size;
      const ctx = canvas.getContext('2d')!;
      const colors = ['#3b82f6', '#1e293b'];
      for (let y = 0; y < cells; y++) {
        for (let x = 0; x < cells; x++) {
          ctx.fillStyle = colors[(x + y) % 2];
          ctx.fillRect(x * cell, y * cell, cell, cell);
          ctx.fillStyle = '#94a3b8';
          ctx.font = '16px monospace';
          ctx.fillText(`${x},${y}`, x * cell + 6, y * cell + 22);
        }
      }
      this.uvTexture = new THREE.CanvasTexture(canvas);
      this.uvTexture.colorSpace = THREE.SRGBColorSpace;
    }
    return this.uvTexture;
  }

  /** 描画バッファを CSS 表示サイズに毎フレーム追従させる
   *  (構築時にウィンドウサイズが未確定な環境や DPI 変更にも耐える) */
  private resizeToDisplaySize() {
    const canvas = this.renderer.domElement;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w === 0 || h === 0) return false;
    const size = this.renderer.getSize(new THREE.Vector2());
    if (size.x !== w || size.y !== h) this.renderer.setSize(w, h, false);
    return true;
  }

  private renderLoop = () => {
    this.rafId = requestAnimationFrame(this.renderLoop);
    if (!this.resizeToDisplaySize()) return;
    const canvasHeight = this.renderer.domElement.clientHeight;
    this.renderer.setClearColor(0x000000, 0);
    for (const pane of this.panes.values()) {
      pane.controls.update();
      const rect = pane.element.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
        continue; // 画面外ペインは描画しない
      }
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      if (width === 0 || height === 0) continue;
      const left = Math.floor(rect.left);
      const bottom = Math.floor(canvasHeight - rect.bottom);
      this.renderer.setViewport(left, bottom, width, height);
      this.renderer.setScissor(left, bottom, width, height);
      const aspect = width / height;
      if (Math.abs(pane.camera.aspect - aspect) > 1e-4) {
        pane.camera.aspect = aspect;
        pane.camera.updateProjectionMatrix();
      }
      this.renderer.render(pane.scene, pane.camera);
    }
  };
}

/** モデルを原点中心・最大径 1 に正規化する(framing 差で比較が濁るのを防ぐ) */
function normalizeIntoUnitBox(object: THREE.Object3D) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  object.position.sub(center);
  object.position.multiplyScalar(1 / maxDim);
  object.scale.multiplyScalar(1 / maxDim);
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  for (const m of Array.isArray(material) ? material : [material]) m.dispose();
}
