import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SiteManifest } from '../data/types';
import { parseVramMeasurement, vramScopeInfo } from '../data/vramScope';

vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'));

import { TaskDetail } from './TaskDetail';

// #72: VRAM 計測口径(legacy / process-group / RunPod exclusive)の混在 manifest で、
// 各セルの VRAM 値に正しい口径ラベルと説明 tooltip が付くこと。数値の補正はしないこと。

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
    entry('triposr', { vram_measurement: { scope: 'inference_process_group' } }),
    entry('trellis1', { vram_measurement: { scope: 'runpod_exclusive_device' } }),
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

it('口径の混在する課題で各セルに正しいラベルとアクセシブルな tooltip が付く', async () => {
  render(<TaskDetail taskId="cartoon-apple" onBack={() => {}} />);

  const legacy = await screen.findByText(/装置計・旧/);
  const process = screen.getByText(/プロセス計/);
  const device = screen.getByText(/専有装置計/);

  // tooltip はキーボード/支援技術から到達可能:
  // focusable(tabIndex=0)+ aria-describedby → role=tooltip の説明本文
  for (const [labelEl, hintPart] of [
    [legacy, 'legacy device total'],
    [process, '共存プロセスは含みません'],
    [device, 'ベースラインを含みます'],
  ] as const) {
    const trigger = labelEl.closest('[aria-describedby]')!;
    expect(trigger.getAttribute('tabindex')).toBe('0');
    const tooltip = document.getElementById(trigger.getAttribute('aria-describedby')!)!;
    expect(tooltip.getAttribute('role')).toBe('tooltip');
    expect(tooltip.textContent).toContain(hintPart);
  }

  // 数値は補正されずそのまま(8GB 表示が 3 件)
  expect(screen.getAllByText(/VRAM 8\.0GB/).length).toBe(3);
});

it('parseVramMeasurement: legacy は field 欠落のみ、壊れた記録は malformed、未知 scope は future', () => {
  expect(parseVramMeasurement({}).kind).toBe('legacy');
  // field があるのに検証を通らない → legacy に落とさずデータ不正を可視化する(PR #82 レビュー指摘)
  expect(parseVramMeasurement({ vram_measurement: 'broken' }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: {} }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: [] }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: { scope: '' } }).kind).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: { scope: 42 } }).kind).toBe('malformed');
  // 既知 scope でも flag の型 drift/typo は malformed(#83: schema drift をパーサで検出)
  expect(
    parseVramMeasurement({
      vram_measurement: { scope: 'inference_process_group', co_resident_processes_included: 'no' },
    }).kind,
  ).toBe('malformed');
  expect(parseVramMeasurement({ vram_measurement: { scope: 'future_scope_v9' } })).toEqual({
    kind: 'future',
    scope: 'future_scope_v9',
  });
  const known = parseVramMeasurement({
    vram_measurement: { scope: 'runpod_exclusive_device', device_baseline_included: true },
  });
  expect(known).toMatchObject({ kind: 'known', scope: 'runpod_exclusive_device' });
});

it('vramScopeInfo は view の kind ごとに正しいラベルを返す', () => {
  expect(vramScopeInfo({ kind: 'legacy' }).label).toBe('装置計・旧');
  expect(vramScopeInfo({ kind: 'malformed' }).label).toBe('口径不明');
  expect(vramScopeInfo({ kind: 'future', scope: 'future_scope_v9' }).label).toBe('future_scope_v9');
  expect(
    vramScopeInfo({
      kind: 'known',
      scope: 'inference_process_group',
      measurement: { scope: 'inference_process_group' },
    }).label,
  ).toBe('プロセス計');
});
