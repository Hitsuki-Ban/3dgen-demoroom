import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SiteManifest } from '../data/types';
import { resetManifestStoreForTests } from '../data/useManifest';

vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'));

import App from '../App';
import { TaskDetail } from './TaskDetail';

// #54: manifest 取得エラーの明示表示・再試行での復帰・failure セルの「生成失敗」表示

const okManifest: SiteManifest = {
  generatedAt: '2026-07-12T00:00:00Z',
  partial: true,
  entries: [
    {
      status: 'success',
      taskId: 'cartoon-apple',
      modelId: 'sf3d',
      glbUrl: '/run-assets/sf3d/cartoon-apple/output.glb',
      glbSizeBytes: 1024,
      metrics: { wallClockSeconds: 12.3, peakVramBytes: 2 ** 30, gpuName: 'TEST GPU' },
      meta: {},
    },
    {
      status: 'failed',
      taskId: 'chrome-espresso-machine',
      modelId: 'partcrafter',
      failure: {
        errorType: 'OutOfMemoryError',
        retryCount: 1,
        startedAt: '2026-07-09T00:00:00Z',
        finishedAt: '2026-07-09T00:05:00Z',
      },
    },
  ],
};

/** テストごとに差し替え可能な fetch 実装 */
let fetchManifest: () => Promise<Response>;

beforeEach(() => {
  resetManifestStoreForTests();
  window.location.hash = '';
  vi.stubGlobal('scrollTo', vi.fn());
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).includes('manifest.json')) return fetchManifest();
      throw new TypeError('offline (test)');
    }),
  );
});

it('manifest 取得失敗でエラーバナーを出し、再試行で同一セッション内復帰する', async () => {
  fetchManifest = () => Promise.reject(new TypeError('network down'));
  render(<App />);

  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain('読み込みに失敗');
  // 誤った正常表示(0/11 実測済み)を出さない
  expect(screen.queryByText(/実測済み/)).toBeNull();

  // ネットワーク復帰後、再試行で通常表示へ
  fetchManifest = async () => new Response(JSON.stringify(okManifest), { status: 200 });
  screen.getByText('再試行').click();
  await screen.findByText(/モデル 1\/11 実測済み/);
  expect(screen.queryByRole('alert')).toBeNull();
});

it('HTTP エラーや不正 JSON もエラーとして表示する', async () => {
  fetchManifest = async () => new Response('<!doctype html>not json', { status: 200 });
  render(<App />);
  expect(await screen.findByRole('alert')).toBeTruthy();
});

it('failure セルは「ベンチ待機中」ではなく「生成失敗」として表示される', async () => {
  fetchManifest = async () => new Response(JSON.stringify(okManifest), { status: 200 });
  render(<TaskDetail taskId="chrome-espresso-machine" onBack={() => {}} />);

  expect(await screen.findByText('生成失敗')).toBeTruthy();
  expect(screen.getByText(/OutOfMemoryError/).textContent).toContain('リトライ 1 回');
  // PartCrafter のカードが待機中扱いになっていないこと
  const failureCard = screen.getByText('生成失敗').closest('div.rounded-lg')!;
  expect(failureCard.textContent).toContain('PartCrafter');
});
