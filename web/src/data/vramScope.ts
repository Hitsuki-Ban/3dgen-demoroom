/** meta.json の optional `vram_measurement` を検証済み view へ refine する(#72/#83)。
 *  schema 正本は bench/src/bench_harness/meta.py(#71)。
 *  raw meta(modal/診断用)と UI が読む validated view の所有範囲をここで分離し、
 *  UI consumer は unknown への cast なしで discriminated union を使う。
 *  口径間の算術補正・暗黙換算は行わない — 表示上の識別だけを行う。 */
import type { RunResult, VramMeasurementMeta } from './types';

export type KnownVramScope = 'inference_process_group' | 'runpod_exclusive_device';

/** 検証済みの計測口径 view。
 *  - legacy: `vram_measurement` field 自体が無い(記録開始前の成果物)
 *  - known: 既知 scope。検証済み measurement を保持
 *  - future: scope は string だが未知(将来の schema。推測で寄せない)
 *  - malformed: field はあるのに検証を通らない(データ不正を隠さず可視化) */
export type VramScopeView =
  | { kind: 'legacy' }
  | { kind: 'known'; scope: KnownVramScope; measurement: VramMeasurementMeta }
  | { kind: 'future'; scope: string }
  | { kind: 'malformed' };

const KNOWN_SCOPES: readonly KnownVramScope[] = ['inference_process_group', 'runpod_exclusive_device'];

function isKnownScope(scope: string): scope is KnownVramScope {
  return (KNOWN_SCOPES as readonly string[]).includes(scope);
}

/** manifest 境界の検証パーサ。untrusted JSON を触るのはこの関数だけ */
export function parseVramMeasurement(meta: RunResult['meta']): VramScopeView {
  if (!('vram_measurement' in meta)) return { kind: 'legacy' };
  const raw: unknown = meta.vram_measurement;
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return { kind: 'malformed' };
  const record = raw as Record<string, unknown>;

  const scope = record['scope'];
  if (typeof scope !== 'string' || scope === '') return { kind: 'malformed' };
  if (!isKnownScope(scope)) return { kind: 'future', scope };

  // 既知 scope は UI が説明に使う flag の型まで検証する(typo/drift は malformed に落とす)
  const baseline = record['device_baseline_included'];
  const coResident = record['co_resident_processes_included'];
  if (baseline !== undefined && typeof baseline !== 'boolean') return { kind: 'malformed' };
  if (coResident !== undefined && typeof coResident !== 'boolean') return { kind: 'malformed' };

  return {
    kind: 'known',
    scope,
    measurement: { scope, device_baseline_included: baseline, co_resident_processes_included: coResident },
  };
}

export interface VramScopeInfo {
  /** VRAM 値に添える短いラベル */
  label: string;
  /** tooltip で出す説明(baseline / 共存プロセスの扱い) */
  hint: string;
}

const KNOWN_INFO: Record<KnownVramScope, VramScopeInfo> = {
  inference_process_group: {
    label: 'プロセス計',
    hint: 'inference process group: 推論プロセスグループのみを合算した値。デバイスのベースラインと共存プロセスは含みません。',
  },
  runpod_exclusive_device: {
    label: '専有装置計',
    hint: 'RunPod exclusive device total: 1 GPU 専有 Pod でのデバイス全体の使用量。デバイスのベースラインを含みます(記録済み)。',
  },
};

/** view → 表示情報。switch の網羅性チェックで kind 追加漏れをコンパイル時に検出する */
export function vramScopeInfo(view: VramScopeView): VramScopeInfo {
  switch (view.kind) {
    case 'legacy':
      return {
        label: '装置計・旧',
        hint: 'legacy device total: 計測口径の記録が始まる前の値。GPU デバイス全体の使用量で、ベースラインや共存プロセスを含み得ます。',
      };
    case 'known':
      return KNOWN_INFO[view.scope];
    case 'future':
      return { label: view.scope, hint: `未知の計測口径: ${view.scope}(meta.json 参照)` };
    case 'malformed':
      return {
        label: '口径不明',
        hint: 'vram_measurement は記録されていますが検証を通りません(メタデータ破損の可能性)。meta.json を確認してください。',
      };
  }
}
