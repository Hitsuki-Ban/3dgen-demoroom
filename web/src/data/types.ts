/**
 * サイトが消費するデータモデル。
 * manifest は bench_harness.site_data が検証済みの site DTO として生成する。
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
  /**
   * ビューア表示時の向き補正(度、XYZ の順で適用)。生成物は書き換えず表示時のみ回転する。
   * **複数課題で一貫した軸慣習が実測確認できたモデルにだけ**設定する(2026-07-11 検証)。
   * TripoSR / Pixal3D のように出力の向きが課題(リファレンス画像のカメラ)に依存する
   * モデルは定数補正が不可能なので設定しない — その挙動自体を展示情報として扱う。
   */
  orientationFix?: { x?: number; y?: number; z?: number };
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
  status: 'success';
  taskId: string;
  modelId: string;
  /** GLB の URL(geo 制限モデルは /restricted/ プレフィックス) */
  glbUrl: string;
  glbSizeBytes: number;
  metrics: {
    wallClockSeconds: number;
    peakVramBytes: number;
    gpuName: string;
  };
  /** Python schema で検証済みの完全な meta.json。meta modal 以外の表示は metrics を使う。 */
  meta: Record<string, unknown>;
  /** 最適化パイプライン導入後に付与される */
  stats?: GeometryStats;
}

export interface RunFailure {
  status: 'failed';
  taskId: string;
  modelId: string;
  failure: {
    errorType: string;
    retryCount: number;
    startedAt: string;
    finishedAt: string;
  };
}

export type SiteDataEntry = RunResult | RunFailure;

export function isRunResult(entry: SiteDataEntry): entry is RunResult {
  return entry.status === 'success';
}

/** bench-harness site-data-snapshot が出力する公開 manifest */
export interface SiteManifest {
  generatedAt: string;
  entries: SiteDataEntry[];
}
