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
 * onProgress にはダウンロード進捗(0..1)を通知する(Content-Length 不明時は呼ばれない) */
export async function loadModel(
  url: string,
  onProgress?: (fraction: number) => void,
): Promise<THREE.Object3D> {
  const res = await fetch(url);
  if (res.status === 451) throw new RegionBlockedError();
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const total = Number(res.headers.get('Content-Length')) || 0;
  let buffer: ArrayBuffer;
  if (res.body && total > 0 && onProgress) {
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.byteLength;
      onProgress(Math.min(received / total, 1));
    }
    const merged = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    buffer = merged.buffer;
  } else {
    buffer = await res.arrayBuffer();
  }
  const gltf = await getLoader().parseAsync(buffer, '');
  return gltf.scene;
}
