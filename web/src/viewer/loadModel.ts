import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

let loader: GLTFLoader | null = null;

function getLoader(): GLTFLoader {
  if (!loader) {
    loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    // TODO(assets pipeline): KTX2Loader(要 transcoder 配置)と DRACOLoader を配線する。
    // 最適化パイプラインの既定は meshopt なので scaffold 段階はこれで足りる。
    // 参照: docs/research/viewer-hosting-merged.md
  }
  return loader;
}

/** 地域制限モデル(Hunyuan3D 2.1 等)のアセットがエッジで HTTP 451 遮断された場合に投げる */
export class RegionBlockedError extends Error {
  constructor() {
    super('ライセンス条項により、この地域ではこのモデルの出力を表示できません');
    this.name = 'RegionBlockedError';
  }
}

/** ベンチ成果物の GLB を読み込む。ViewerCore.addPane にそのまま渡せる Object3D を返す。
 * onProgress にはダウンロード進捗(0..1)を通知する(Content-Length 不明時は呼ばれない)。
 * signal で進行中のダウンロードを中断できる(ペイン unmount 時の帯域・メモリ浪費防止 #52) */
export async function loadModel(
  url: string,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<THREE.Object3D> {
  const res = await fetch(url, { signal });
  if (res.status === 451) throw new RegionBlockedError();
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const total = Number(res.headers.get('Content-Length')) || 0;
  let buffer: ArrayBuffer;
  if (res.body && total > 0 && onProgress) {
    // Content-Length が既知なら 1 回だけ確保して直接書き込む
    // (chunks 配列+結合バッファの二重保持だと最大 GLB 568MB で一時 ~2 倍のメモリを食う #52)
    const reader = res.body.getReader();
    let data = new Uint8Array(total);
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (received + value.byteLength > data.length) {
        // Content-Length が実体より小さい異常系: 2 倍に伸長して続行
        const grown = new Uint8Array(Math.max(data.length * 2, received + value.byteLength));
        grown.set(data.subarray(0, received));
        data = grown;
      }
      data.set(value, received);
      received += value.byteLength;
      onProgress(Math.min(received / total, 1));
    }
    buffer = data.buffer.slice(0, received) as ArrayBuffer;
  } else {
    buffer = await res.arrayBuffer();
  }
  const gltf = await getLoader().parseAsync(buffer, '');
  return gltf.scene;
}

/** parse 済みだが表示しない(キャンセル済みペイン等の)Object3D の GPU/CPU リソースを解放する */
export function disposeObject(root: THREE.Object3D) {
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value && typeof value === 'object' && 'isTexture' in value) (value as THREE.Texture).dispose();
      }
      material.dispose();
    }
  });
}
