/** meta.json の optional `vram_measurement` を検証済み view へ refine する(#72/#83)。
 *  schema 正本は bench/src/bench_harness/meta.py(#71)。
 *  raw meta(modal/診断用)と UI が読む validated view の所有範囲をここで分離し、
 *  UI consumer は unknown への cast なしで discriminated union を使う。
 *  口径間の算術補正・暗黙換算は行わない — 表示上の識別だけを行う。 */
import type { RunResult, VramMeasurementMeta } from './types';

export type KnownVramScope = 'inference_process_group' | 'runpod_exclusive_device';

/** 検証済みの計測口径 view。
 *  - legacy: `vram_measurement` field 自体が無い(記録開始前の成果物)
 *  - known: 既知 scope。meta.py の canonical tuple(method+flags)まで検証済み
 *  - future: scope は string だが未知(将来の schema。推測で寄せない)
 *  - malformed: field はあるのに検証を通らない(データ不正を隠さず可視化) */
export type VramScopeView =
  | { kind: 'legacy' }
  | { kind: 'known'; scope: KnownVramScope; measurement: VramMeasurementMeta }
  | { kind: 'future'; scope: string }
  | { kind: 'malformed' };

/** meta.py が要求する scope ごとの正確な組(method / flag)。
 *  組が崩れた record を known として通すと、UI の説明(baseline/共存プロセスの
 *  含む・含まない)が実データと矛盾し得る(PR #84 レビュー指摘) */
const CANONICAL: Record<
  KnownVramScope,
  { method: string; deviceBaselineIncluded: boolean; coResidentProcessesIncluded: boolean }
> = {
  inference_process_group: {
    method: 'nvidia_smi_compute_process_mib_sampled_sum',
    deviceBaselineIncluded: false,
    coResidentProcessesIncluded: false,
  },
  runpod_exclusive_device: {
    method: 'nvidia_smi_device_memory_mib_sampled',
    deviceBaselineIncluded: true,
    coResidentProcessesIncluded: true,
  },
};

function isKnownScope(scope: string): scope is KnownVramScope {
  return scope in CANONICAL;
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

  // 既知 scope は canonical tuple と厳密一致を要求する(欠落・矛盾・drift は malformed)
  const canonical = CANONICAL[scope];
  if (
    record['method'] !== canonical.method ||
    record['device_baseline_included'] !== canonical.deviceBaselineIncluded ||
    record['co_resident_processes_included'] !== canonical.coResidentProcessesIncluded
  ) {
    return { kind: 'malformed' };
  }

  return {
    kind: 'known',
    scope,
    measurement: {
      scope,
      method: canonical.method,
      device_baseline_included: canonical.deviceBaselineIncluded,
      co_resident_processes_included: canonical.coResidentProcessesIncluded,
    },
  };
}

export interface VramScopeInfo {
  /** tooltip 冒頭に出す短いラベル */
  label: string;
  /** tooltip 本文(baseline / 共存プロセスの扱い)。短く保つ */
  hint: string;
  /** データ品質への注意が必要な view(malformed)は表示を強調する */
  attention: boolean;
}

const KNOWN_INFO: Record<KnownVramScope, VramScopeInfo> = {
  inference_process_group: {
    label: 'プロセス計',
    hint: '推論プロセス群のみの合算(ベースライン・共存プロセスは含まず)',
    attention: false,
  },
  runpod_exclusive_device: {
    label: '専有装置計',
    hint: '1 GPU 専有 Pod のデバイス全体量(ベースライン込み)',
    attention: false,
  },
};

/** view → 表示情報。switch の網羅性チェックで kind 追加漏れをコンパイル時に検出する */
export function vramScopeInfo(view: VramScopeView): VramScopeInfo {
  switch (view.kind) {
    case 'legacy':
      return {
        label: '旧計測',
        hint: 'GPU デバイス全体の使用量(他プロセスを含み得る)',
        attention: false,
      };
    case 'known':
      return KNOWN_INFO[view.scope];
    case 'future':
      return { label: view.scope, hint: '未知の計測口径(meta.json 参照)', attention: false };
    case 'malformed':
      return { label: '口径不明', hint: '計測記録が読み取れません(meta.json 参照)', attention: true };
  }
}
