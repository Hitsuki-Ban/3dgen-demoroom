import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export type DisplayMode = 'pbr' | 'toon' | 'wireframe' | 'matcap' | 'normal' | 'uv';

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
  /** toon モード用ライト(環境マップは MeshToonMaterial に効かないため) */
  toonLights: THREE.Group;
  /** 正規化前のモデル最大径。輪郭線の太さをワールド基準に揃えるのに使う */
  maxDim: number;
  /** モデル別の向き補正(ラジアン)。トグルで生の向きと切り替えるため保持する */
  orientationFix: THREE.Euler | null;
}

const CAMERA_HOME = new THREE.Vector3(1.2, 0.9, 1.6);
const ZERO_EULER = new THREE.Euler();

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
  /** モデル別向き補正の適用有無(既定 ON。OFF で生成物の生の向きを表示) */
  private orientationFixEnabled = true;
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

  /** ペインを登録し、モデル(正規化済みで modelRoot に追加される)を表示する。
   *  orientationFixDeg はモデル別の向き補正(度)。適用有無はコアのトグルに従う */
  addPane(
    element: HTMLElement,
    object: THREE.Object3D,
    orientationFixDeg?: { x?: number; y?: number; z?: number },
  ): number {
    const id = this.nextId++;
    const scene = new THREE.Scene();
    scene.environment = this.envMap;

    const d = Math.PI / 180;
    const orientationFix = orientationFixDeg
      ? new THREE.Euler((orientationFixDeg.x ?? 0) * d, (orientationFixDeg.y ?? 0) * d, (orientationFixDeg.z ?? 0) * d)
      : null;
    if (orientationFix && this.orientationFixEnabled) object.rotation.copy(orientationFix);

    const modelRoot = new THREE.Group();
    const maxDim = normalizeIntoUnitBox(object);
    modelRoot.add(object);
    scene.add(modelRoot);

    const toonLights = new THREE.Group();
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    keyLight.position.set(2, 3, 2.5);
    toonLights.add(keyLight, new THREE.AmbientLight(0xffffff, 0.6));
    toonLights.visible = false;
    scene.add(toonLights);

    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 50);
    camera.position.copy(CAMERA_HOME);

    const controls = new OrbitControls(camera, element);
    controls.enableDamping = true;
    controls.addEventListener('change', () => this.broadcastCamera(id));

    const pane: Pane = { id, element, scene, camera, controls, modelRoot, toonLights, maxDim, orientationFix };
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
      if (o instanceof THREE.Mesh && !o.userData.isOutline) {
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
    this.emitChange();
  }

  /** UI(ツールバー等)が現在状態へ同期するためのゲッター。
   *  mode / cameraSync の情報源は常にこのクラス(React 側で二重管理しない) */
  getDisplayMode(): DisplayMode {
    return this.mode;
  }

  getCameraSync(): boolean {
    return this.cameraSync;
  }

  /** 向き補正の ON/OFF。OFF で「モデルが出力した生の向き」を表示する(比較の公平性検分用) */
  setOrientationFixEnabled(enabled: boolean) {
    if (this.orientationFixEnabled === enabled) return;
    this.orientationFixEnabled = enabled;
    for (const pane of this.panes.values()) {
      if (!pane.orientationFix) continue;
      const object = pane.modelRoot.children.find((c) => !c.userData.isOutline);
      if (!object) continue;
      object.rotation.copy(enabled ? pane.orientationFix : ZERO_EULER);
      // 回転でバウンディングボックスが変わるので正規化をやり直す
      object.position.set(0, 0, 0);
      object.scale.set(1, 1, 1);
      normalizeIntoUnitBox(object);
    }
    this.emitChange();
  }

  getOrientationFixEnabled(): boolean {
    return this.orientationFixEnabled;
  }

  private changeListeners = new Set<() => void>();

  /** mode / cameraSync の変更通知を購読する(解除関数を返す)。
   *  ツールバーはどこで remount されても・誰が状態を変えても、常にコア状態を映す */
  subscribeChange(listener: () => void): () => void {
    this.changeListeners.add(listener);
    return () => this.changeListeners.delete(listener);
  }

  private emitChange() {
    for (const listener of this.changeListeners) listener();
  }

  setCameraSync(enabled: boolean) {
    this.cameraSync = enabled;
    if (enabled && this.panes.size > 0) {
      const [first] = this.panes.values();
      this.broadcastCamera(first.id, true);
    }
    this.emitChange();
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
    pane.toonLights.visible = mode === 'toon';
    // traverse 中に子(輪郭線メッシュ)を追加すると走査が乱れるので、先にメッシュを収集する
    const meshes: THREE.Mesh[] = [];
    pane.modelRoot.traverse((o) => {
      if (o instanceof THREE.Mesh && !o.userData.isOutline) meshes.push(o);
    });
    for (const o of meshes) {
      if (!o.userData.originalMaterial) o.userData.originalMaterial = o.material;
      const original = o.userData.originalMaterial as THREE.Material;
      // 法線を持たない GLB(glTF 的には flat shading 想定)があるため、
      // ライティング/法線系の表示モードでは表示用にスムーズ法線を遅延計算する。
      // 一度計算すれば attribute が付くので再計算されない。生成物ファイルは不変。
      if ((mode === 'toon' || mode === 'matcap' || mode === 'normal') && !o.geometry.attributes.normal) {
        o.geometry.computeVertexNormals();
      }
      // 前のモードの輪郭線メッシュを外す(ジオメトリは本体と共有なので dispose しない)
      for (const child of [...o.children]) {
        if (child.userData.isOutline) {
          o.remove(child);
          disposeMaterial((child as THREE.Mesh).material);
        }
      }
      // モード用に生成した差し替えマテリアルはここで破棄する(共有テクスチャは dispose されない)
      if (o.material !== original) disposeMaterial(o.material);
      switch (mode) {
        case 'pbr':
          o.material = original;
          break;
        case 'toon': {
          o.material = new THREE.MeshToonMaterial({ color: 0xe8e4dc, gradientMap: this.getToonGradient() });
          if (o.geometry.attributes.normal) {
            const outline = new THREE.Mesh(o.geometry, createOutlineMaterial(pane.maxDim * 0.004));
            outline.userData.isOutline = true;
            outline.raycast = () => {};
            o.add(outline);
          }
          break;
        }
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
    }
  }

  private toonGradient: THREE.Texture | null = null;

  /** 3 段のセルシェーディング用グラデーション */
  private getToonGradient(): THREE.Texture {
    if (!this.toonGradient) {
      const tex = new THREE.DataTexture(new Uint8Array([80, 170, 255]), 3, 1, THREE.RedFormat);
      tex.minFilter = THREE.NearestFilter;
      tex.magFilter = THREE.NearestFilter;
      tex.needsUpdate = true;
      this.toonGradient = tex;
    }
    return this.toonGradient;
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
    // まず scissor を外して canvas 全体を透明クリアする。
    // ペインの scissor 領域しか消去しないと、スクロールやペインの unmount で
    // 移動・消滅した位置に前フレームの絵が残像として残る(#49)
    this.renderer.setScissorTest(false);
    this.renderer.clear(true, true, false);
    this.renderer.setScissorTest(true);
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

/** モデルを原点中心・最大径 1 に正規化する(framing 差で比較が濁るのを防ぐ)。正規化前の最大径を返す */
function normalizeIntoUnitBox(object: THREE.Object3D): number {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  object.position.sub(center);
  object.position.multiplyScalar(1 / maxDim);
  object.scale.multiplyScalar(1 / maxDim);
  return maxDim;
}

/**
 * インバーテッドハル方式の輪郭線マテリアル。
 * 背面を法線方向に押し出して描く古典的なトゥーン輪郭。EdgesGeometry と違い
 * 数百万ポリゴンのメッシュでも追加ジオメトリ生成なしで動く。
 * thickness はメッシュのローカル空間単位(正規化前の最大径 × 係数を渡す)。
 */
function createOutlineMaterial(thickness: number): THREE.Material {
  const material = new THREE.MeshBasicMaterial({ color: 0x0b0d10, side: THREE.BackSide });
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>\n\ttransformed += normalize(normal) * ${thickness.toExponential(6)};`,
    );
  };
  return material;
}

function disposeMaterial(material: THREE.Material | THREE.Material[]) {
  for (const m of Array.isArray(material) ? material : [material]) m.dispose();
}
