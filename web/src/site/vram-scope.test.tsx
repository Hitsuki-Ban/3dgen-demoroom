import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SiteManifest } from '../data/types';
import { parseVramMeasurement, vramScopeInfo } from '../data/vramScope';

vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'));

import { TaskDetail } from './TaskDetail';

// #72/#83: VRAM 計測口径の検証パーサと注記マーク表示。
// known scope は meta.py の canonical tuple(method+flags)と厳密一致を要求する(PR #84 レビュー指摘)。

const PROCESS_CANONICAL = {
  scope: 'inference_process_group',
  method: 'nvidia_smi_compute_process_mib_sampled_sum',
  device_baseline_included: false,
  co_resident_processes_included: false,
};
const RUNPOD_CANONICAL = {
  scope: 'runpod_exclusive_device',
  method: 'nvidia_smi_device_memory_mib_sampled',
  device_baseline_included: true,
  co_resident_processes_included: true,
};

function entry(modelId: string, meta: Record<string, unknown>) {
  return {
    status: 'success' as const,
    taskId: 'cartoon-apple',
    modelId,
    glbUrl: `/run-assets/${modelId}/cartoon-apple/output.glb`,
    glbSizeBytes: 1024,
    metrics: { wallClockSeconds: 10, peakVramBytes: 8 * 2 ** 30, gpuName: 'TEST GPU' },
    meta,
  };
}

const manifest: SiteManifest = {
  generatedAt: '2026-07-12T00:00:00Z',
  partial: true,
  entries: [
    entry('sf3d', {}), // field なし = legacy
    entry('triposr', { vram_measurement: PROCESS_CANONICAL }),
    entry('trellis1', { vram_measurement: RUNPOD_CANONICAL }),
  ],
};

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).includes('manifest.json')) {
        return new Response(JSON.stringify(manifest), { status: 200 });
      }
      throw new TypeError('offline (test)');
    }),
  );
});

it('口径の混在する課題で、各セルの「!」マークからアクセシブルな注記に到達できる', async () => {
  render(<TaskDetail taskId="cartoon-apple" onBack={() => {}} />);
  await screen.findByText(/モデル別出力/);

  // 口径ラベルはインライン常時表示しない(オーナー UX FB)— tooltip の中にだけ出る
  const markers = await screen.findAllByLabelText('VRAM 計測口径の注記');
  expect(markers.length).toBe(3);

  const tooltipTexts = markers.map((marker) => {
    // focusable + aria-describedby → role=tooltip 本文(キーボード/支援技術から到達可能)
    expect(marker.getAttribute('tabindex')).toBe('0');
    const tooltip = document.getElementById(marker.getAttribute('aria-describedby')!)!;
    expect(tooltip.getAttribute('role')).toBe('tooltip');
    return tooltip.textContent ?? '';
  });
  expect(tooltipTexts.some((t) => t.includes('旧計測'))).toBe(true);
  expect(tooltipTexts.some((t) => t.includes('プロセス計'))).toBe(true);
  expect(tooltipTexts.some((t) => t.includes('専有装置計'))).toBe(true);

  // 数値は補正されずそのまま(8GB 表示が 3 件)
  expect(screen.getAllByText(/VRAM 8\.0GB/).length).toBe(3);
});

it('parseVramMeasurement: legacy は field 欠落のみ、malformed は隠さない', () => {
  expect(parseVramMeasurement({}).kind).toBe('legacy');
  // field があるのに検証を通らない → legacy に落とさずデータ不正を可視化(PR #82 指摘)
  expect(parseVramMeasurement({ vram_measurement: 'broken' }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: {} }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: [] }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: { scope: '' } }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: { scope: 42 } }).kind).toBe('malformed');
});

it('parseVramMeasurement: known は canonical tuple と厳密一致(欠落・矛盾・drift は malformed)', () => {
  expect(parseVramMeasurement({ vram_measurement: PROCESS_CANONICAL })).toMatchObject({
    kind: 'known',
    scope: 'inference_process_group',
  });
  expect(parseVramMeasurement({ vram_measurement: RUNPOD_CANONICAL })).toMatchObject({
    kind: 'known',
    scope: 'runpod_exclusive_device',
  });

  // flag 欠落(scope だけ)は known にしない
  expect(parseVramMeasurement({ vram_measurement: { scope: 'inference_process_group' } }).kind).toBe('malformed');
  // 実データと矛盾する flag(process なのに baseline 込み)を known として説明しない(PR #84 指摘)
  expect(
    parseVramMeasurement({
      vram_measurement: { ...PROCESS_CANONICAL, device_baseline_included: true },
    }).kind,
  ).toBe('malformed');
  // scope と method の組違い
  expect(
    parseVramMeasurement({
      vram_measurement: { ...PROCESS_CANONICAL, method: RUNPOD_CANONICAL.method },
    }).kind,
  ).toBe('malformed');
  // flag の型 drift/typo
  expect(
    parseVramMeasurement({
      vram_measurement: { ...RUNPOD_CANONICAL, co_resident_processes_included: 'yes' },
    }).kind,
  ).toBe('malformed');
});

it('parseVramMeasurement: 未知 scope は future として生の値を保持する', () => {
  expect(parseVramMeasurement({ vram_measurement: { scope: 'future_scope_v9' } })).toEqual({
    kind: 'future',
    scope: 'future_scope_v9',
  });
});

it('vramScopeInfo: malformed だけ attention、それ以外は通常表示', () => {
  expect(vramScopeInfo({ kind: 'legacy' })).toMatchObject({ label: '旧計測', attention: false });
  expect(vramScopeInfo({ kind: 'malformed' })).toMatchObject({ label: '口径不明', attention: true });
  expect(vramScopeInfo({ kind: 'future', scope: 'x_v9' })).toMatchObject({ label: 'x_v9', attention: false });
  expect(
    vramScopeInfo({
      kind: 'known',
      scope: 'runpod_exclusive_device',
      measurement: RUNPOD_CANONICAL,
    }).label,
  ).toBe('専有装置計');
});
