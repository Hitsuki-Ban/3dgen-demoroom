/** meta.json の optional `vram_measurement` から VRAM 計測口径の表示情報を導く(#72)。
 *  schema 正本は bench/src/bench_harness/meta.py(#71)。
 *  口径間の算術補正・暗黙換算は行わない — 表示上の識別だけを行う。 */

export interface VramScopeInfo {
  /** VRAM 値に添える短いラベル */
  label: string;
  /** hover で出す説明(baseline / 共存プロセスの扱い) */
  hint: string;
}

const LEGACY: VramScopeInfo = {
  label: '装置計・旧',
  hint: 'legacy device total: 計測口径の記録が始まる前の値。GPU デバイス全体の使用量で、ベースラインや共存プロセスを含み得ます。',
};

const SCOPES: Record<string, VramScopeInfo> = {
  inference_process_group: {
    label: 'プロセス計',
    hint: 'inference process group: 推論プロセスグループのみを合算した値。デバイスのベースラインと共存プロセスは含みません。',
  },
  runpod_exclusive_device: {
    label: '専有装置計',
    hint: 'RunPod exclusive device total: 1 GPU 専有 Pod でのデバイス全体の使用量。デバイスのベースラインを含みます(記録済み)。',
  },
};

export function vramScopeInfo(meta: Record<string, unknown>): VramScopeInfo {
  const vm = meta['vram_measurement'];
  if (!vm || typeof vm !== 'object') return LEGACY;
  const scope = (vm as Record<string, unknown>)['scope'];
  if (typeof scope !== 'string') return LEGACY;
  // 未知の scope は推測でどれかに寄せず、生の値をそのまま見せる
  return SCOPES[scope] ?? { label: scope, hint: `未知の計測口径: ${scope}(meta.json 参照)` };
}
