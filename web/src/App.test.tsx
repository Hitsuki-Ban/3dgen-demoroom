import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { SiteManifest } from './data/types';

// jsdom に WebGL は無いので ViewerCore はスタブ(#59 の mount/dispose 検証にも使う)
vi.mock('./viewer/ViewerCore', () => import('./test/viewer-core-stub'));

import App from './App';
import { ViewerCore } from './test/viewer-core-stub';

// #59: Viewer(three.js/canvas/RAF)は課題詳細スコープでのみ生成される。
// homepage → detail → back のライフサイクルで canvas 生成と dispose を検証する。

const manifest: SiteManifest = {
  generatedAt: '2026-07-12T00:00:00Z',
  partial: true,
  entries: [],
};

beforeEach(() => {
  window.location.hash = '';
  vi.stubGlobal('scrollTo', vi.fn());
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

it('homepage では canvas/ViewerCore を作らず、詳細で生成・戻るで dispose する', async () => {
  render(<App />);

  // homepage: ギャラリーは出るが viewer canvas は存在しない
  await screen.findByText(/ベンチマーク課題/);
  expect(document.querySelector('#viewer-canvas')).toBeNull();
  expect(ViewerCore.instances.length).toBe(0);

  // 課題を開く(lazy チャンクのロードを待つ)
  screen.getByText('cartoon-apple').click();
  await screen.findByText(/モデル別出力/);
  await waitFor(() => expect(document.querySelector('#viewer-canvas')).not.toBeNull());
  expect(ViewerCore.instances.length).toBe(1);

  // 一覧へ戻ると canvas は消え、core は dispose される
  screen.getByText('← 課題一覧に戻る').click();
  await screen.findByText(/ベンチマーク課題/);
  expect(document.querySelector('#viewer-canvas')).toBeNull();
  expect(ViewerCore.instances[0].disposed).toBe(true);

  // もう一度開けば新しい core が作られる(再訪の回帰)
  screen.getByText('crusty-bread-loaf').click();
  await waitFor(() => expect(document.querySelector('#viewer-canvas')).not.toBeNull());
  expect(ViewerCore.instances.length).toBe(2);
  expect(ViewerCore.instances[1].disposed).toBe(false);
});
