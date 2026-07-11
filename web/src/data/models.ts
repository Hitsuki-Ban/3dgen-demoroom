import type { ModelInfo } from './types';
import modelRegistry from './model-registry.json';

/**
 * ベンチ対象モデルレジストリ v1(11 モデル)。
 * 根拠: docs/research/models-merged.md(2026-07-08 確定)
 * 並び順 = サイト表示順: textured(平均生成時間の昇順)→ パーツ分離 → geometry-only
 */
export const MODELS: ModelInfo[] = [
  {
      id: 'sf3d',
      orientationFix: { y: 180 },
      name: 'Stable Fast 3D',
      org: 'Stability AI',
      input: 'image',
      license: {
        name: 'Stability Community License',
        note: '商用は要登録、年商 $1M 超は Enterprise License 必須',
      },
      badges: ['license-conditional'],
      status: 'planned',
      vramNote: '~6–7GB',
    },
  {
      id: 'triposr',
      name: 'TripoSR',
      org: 'Tripo / Stability AI',
      input: 'image',
      license: { name: 'MIT' },
      badges: [],
      status: 'planned',
      vramNote: '~6GB(速度基準線)',
    },
  {
      id: 'trellis1',
      name: 'TRELLIS',
      org: 'Microsoft',
      input: 'text+image',
      license: { name: 'MIT' },
      badges: ['text-to-3d', '3dgs'],
      status: 'planned',
      vramNote: '~16GB',
    },
  {
      id: '3dtopia-xl',
      name: '3DTopia-XL',
      org: 'Shanghai AI Lab',
      input: 'text+image',
      license: { name: 'Apache-2.0' },
      badges: ['text-to-3d'],
      status: 'planned',
    },
  {
      id: 'hunyuan3d-21',
      name: 'Hunyuan3D 2.1',
      org: 'Tencent',
      input: 'image',
      license: {
        name: 'Tencent Hunyuan3D 2.1 Community License',
        note: 'ライセンス 5(c) 条により EU / UK / 韓国では生成物を表示できません(エッジでブロック)',
      },
      badges: ['geo-restricted'],
      status: 'planned',
      vramNote: '~29GB(段階ロード / A100 fallback)',
    },
  {
      id: 'trellis2',
      name: 'TRELLIS.2-4B',
      org: 'Microsoft',
      input: 'image',
      license: { name: 'MIT' },
      badges: [],
      status: 'planned',
      vramNote: '≥24GB',
    },
  {
      id: 'step1x-3d',
      name: 'Step1X-3D',
      org: 'StepFun',
      input: 'image',
      license: { name: 'Apache-2.0' },
      badges: [],
      status: 'planned',
      vramNote: '~27–29GB',
    },
  {
      id: 'pixal3d',
      name: 'Pixal3D',
      org: 'TencentARC',
      input: 'image',
      license: { name: 'MIT' },
      badges: [],
      status: 'planned',
      vramNote: '標準 1536 / low-VRAM 1024',
    },
  {
      id: 'partcrafter',
      name: 'PartCrafter',
      org: 'CMU ほか',
      input: 'image',
      license: { name: 'MIT' },
      badges: [],
      status: 'planned',
      vramNote: '≥8GB(パーツ分離出力)',
    },
  {
      id: 'triposg',
      name: 'TripoSG',
      org: 'VAST-AI',
      input: 'image',
      license: { name: 'MIT' },
      badges: ['geometry-only'],
      status: 'planned',
      vramNote: '~8GB',
    },
  {
      id: 'direct3d-s2',
      name: 'Direct3D-S2',
      org: 'DreamTech',
      input: 'image',
      license: { name: 'MIT' },
      badges: ['geometry-only'],
      status: 'planned',
      vramNote: '512³: ~10GB / 1024³: ~24GB',
    },
];

const registeredIds = modelRegistry.join(',');
const modelIds = MODELS.map((model) => model.id).join(',');
if (modelIds !== registeredIds) {
  throw new Error(`MODELS must match model-registry.json order: expected ${registeredIds}, received ${modelIds}`);
}

export const BADGE_LABELS: Record<string, { label: string; className: string }> = {
  'geometry-only': { label: 'geometry-only', className: 'bg-slate-700 text-slate-200' },
  'geo-restricted': { label: '地域制限', className: 'bg-amber-900/70 text-amber-200' },
  'license-conditional': { label: 'ライセンス条件付き', className: 'bg-orange-900/70 text-orange-200' },
  'text-to-3d': { label: 'text-to-3D', className: 'bg-sky-900/70 text-sky-200' },
  '3dgs': { label: '3DGS', className: 'bg-violet-900/70 text-violet-200' },
};
