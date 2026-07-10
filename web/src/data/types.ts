/**
 * サイトが消費するデータモデル。
 * RunMeta は bench/src/bench_harness/meta.py の REQUIRED_META_KEYS と 1:1 対応。
 * GeometryStats はオフラインの gltf-transform inspect から生成される(パイプライン PR で実装)。
 */

export type Difficulty = 1 | 2 | 3;

export interface TaskInfo {
  id: string;
  category: string;
  /** 正準プロンプト(EN) — tasks/tasks.json と同一 */
  prompt: string;
  /** 検証ポイント(JP) — サイト表示用 */
  probe: string;
  difficulty: Difficulty;
  /** リファレンス画像 URL(dev: vite ミドルウェア / prod: R2) */
  referenceImage: string;
}

export type ModelBadge =
  | 'geometry-only'
  | 'geo-restricted'
  | 'license-conditional'
  | 'text-to-3d'
  | '3dgs';

export interface ModelInfo {
  id: string;
  name: string;
  org: string;
  input: 'image' | 'text' | 'text+image';
  license: {
    /** 表示名(例: "MIT", "Apache-2.0", "Tencent Community License") */
    name: string;
    /** コードと重みでライセンスが違う場合などの注記 */
    note?: string;
  };
  badges: ModelBadge[];
  /** ベンチ実行状況。results が manifest に載るまでは 'planned' */
  status: 'planned' | 'running' | 'done' | 'excluded';
  vramNote?: string;
}

/** bench の meta.json(REQUIRED_META_KEYS + OPTIONAL_META_KEYS)と対応 */
export interface RunMeta {
  task_id: string;
  model_id: string;
  model_git_commit: string;
  weights_revision: string;
  gpu_name: string;
  wall_clock_seconds: number;
  peak_vram_bytes: number;
  seed: number;
  parameters: Record<string, unknown>;
  retry_count: number;
  torch_version: string;
  torch_cuda_version: string;
  torch_cuda_arch_list: string[];
  attention_backend: string;
  started_at: string;
  finished_at: string;
  license_file: string;
  /** OPTIONAL_META_KEYS: 外部依存(HF リポ等)の取得時 revision 記録。trellis2 / pixal3d 等が出力する */
  external_weight_revisions?: Record<string, string>;
  external_code_revisions?: Record<string, string>;
}

/** gltf-transform inspect から抽出(最適化パイプラインで生成) */
export interface GeometryStats {
  triangles: number;
  vertices: number;
  meshes: number;
  materials: number;
  textures: { slot: string; width: number; height: number }[];
  rawSizeBytes: number;
  optimizedSizeBytes: number;
}

export interface RunResult {
  taskId: string;
  modelId: string;
  /** GLB の URL(geo 制限モデルは /restricted/ プレフィックス) */
  glbUrl: string;
  glbSizeBytes: number;
  meta: RunMeta;
  /** 最適化パイプライン導入後に付与される */
  stats?: GeometryStats;
}

/** ビルド時に生成される manifest(scripts/build-manifest.mjs が出力) */
export interface SiteManifest {
  generatedAt: string;
  results: RunResult[];
}
