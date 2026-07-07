import * as THREE from 'three';

/**
 * ベンチ成果物(GLB)が届くまでの開発用ダミー。
 * 「同じ課題を品質の違うモデルが生成した」状況を、細分化レベルと材質の違う
 * トーラスノットで擬似的に再現する。
 */
export interface DummySpec {
  name: string;
  badge?: string;
  build: () => THREE.Object3D;
}

function knot(tubularSegments: number, radialSegments: number, material: THREE.Material): THREE.Object3D {
  const geometry = new THREE.TorusKnotGeometry(0.4, 0.14, tubularSegments, radialSegments);
  return new THREE.Mesh(geometry, material);
}

export const DUMMY_MODELS: DummySpec[] = [
  {
    name: 'model-alpha',
    build: () => knot(320, 48, new THREE.MeshStandardMaterial({ color: 0xb87333, metalness: 0.9, roughness: 0.25 })),
  },
  {
    name: 'model-beta',
    build: () => knot(160, 24, new THREE.MeshStandardMaterial({ color: 0x8fb3ff, metalness: 0.1, roughness: 0.6 })),
  },
  {
    name: 'model-gamma',
    badge: 'geometry-only',
    build: () => knot(96, 16, new THREE.MeshStandardMaterial({ color: 0xcccccc, metalness: 0.0, roughness: 0.9 })),
  },
  {
    name: 'model-delta',
    build: () => knot(48, 10, new THREE.MeshStandardMaterial({ color: 0x74c69d, metalness: 0.3, roughness: 0.45 })),
  },
  {
    name: 'model-epsilon',
    badge: 'geo-restricted',
    build: () => knot(240, 36, new THREE.MeshStandardMaterial({ color: 0xe0aaff, metalness: 0.6, roughness: 0.3 })),
  },
  {
    name: 'model-zeta',
    build: () => knot(24, 6, new THREE.MeshStandardMaterial({ color: 0xf4a261, metalness: 0.2, roughness: 0.75 })),
  },
];
