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

/** ベンチ成果物の GLB を読み込む。ViewerCore.addPane にそのまま渡せる Object3D を返す */
export async function loadModel(url: string): Promise<THREE.Object3D> {
  const gltf = await getLoader().loadAsync(url);
  return gltf.scene;
}
