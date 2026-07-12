import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SiteManifest } from '../data/types';
import { vramScopeInfo } from '../data/vramScope';

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

it('vramScopeInfo: legacy は field 欠落のみ。壊れた記録は「口径不明」、未知 scope は生の値', () => {
  expect(vramScopeInfo({}).label).toBe('装置計・旧');
  // field があるのに読めない → legacy に落とさずデータ不正を可視化する(PR #82 レビュー指摘)
  expect(vramScopeInfo({ vram_measurement: 'broken' }).label).toBe('口径不明');
  expect(vramScopeInfo({ vram_measurement: {} }).label).toBe('口径不明');
  expect(vramScopeInfo({ vram_measurement: { scope: '' } }).label).toBe('口径不明');
  expect(vramScopeInfo({ vram_measurement: { scope: 42 } }).label).toBe('口径不明');
  expect(vramScopeInfo({ vram_measurement: { scope: 'future_scope_v9' } }).label).toBe('future_scope_v9');
});
