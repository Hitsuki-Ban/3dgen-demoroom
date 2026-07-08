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

/** ベンチ成果物の GLB を読み込む。ViewerCore.addPane にそのまま渡せる Object3D を返す */
export async function loadModel(url: string): Promise<THREE.Object3D> {
  const res = await fetch(url);
  if (res.status === 451) throw new RegionBlockedError();
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buffer = await res.arrayBuffer();
  const gltf = await getLoader().parseAsync(buffer, '');
  return gltf.scene;
}
