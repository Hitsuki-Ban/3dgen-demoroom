import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { MODELS } from '../data/models';
import type { SiteManifest } from '../data/types';

// TaskDetail は ViewerProvider を内包する(#59)が、jsdom に WebGL は無いので
// ViewerCore を API 互換スタブへ差し替える
vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'));

import { TaskDetail } from './TaskDetail';

// focus 表示中に hash で別課題へ移動すると、task-reset effect より先に
// 旧 view state のまま再描画される。新課題側にフォーカス対象の result が
// 無い(部分 manifest・failure セル)場合にクラッシュしない回帰テスト(PR #65 レビュー指摘)。

const MODEL = MODELS[0];
const TASK_A = 'cartoon-apple';
const TASK_B = 'crusty-bread-loaf'; // MODEL の result を意図的に持たせない課題

const manifest: SiteManifest = {
  generatedAt: '2026-07-12T00:00:00Z',
  partial: true,
  entries: [
    {
      status: 'success',
      taskId: TASK_A,
      modelId: MODEL.id,
      glbUrl: `/run-assets/${MODEL.id}/${TASK_A}/output.glb`,
      glbSizeBytes: 1024,
      metrics: { wallClockSeconds: 12.3, peakVramBytes: 2 ** 30, gpuName: 'TEST GPU' },
      meta: {},
    },
  ],
};

beforeEach(() => {
  // manifest だけ返し、GLB 取得は失敗させる(ペインは error 表示になるだけでテスト対象外)
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

it('focus 表示中に result の無い課題へ切り替えてもクラッシュせずグリッドへ戻る', async () => {
  const { rerender } = render(<TaskDetail taskId={TASK_A} onBack={() => {}} />);

  // manifest ロード後、⛶ で単体フォーカスへ
  const focusButton = await screen.findByTitle('このモデルを単体で大きく表示');
  focusButton.click();
  expect(await screen.findByText(`${TASK_A} — ${MODEL.name}`)).toBeTruthy();

  // 旧 view(focus)が残ったまま taskId だけ変わる = hash 直遷移の再現。
  // guard が無いと resultByModel.get(...)! が undefined になり render 中に throw する
  rerender(<TaskDetail taskId={TASK_B} onBack={() => {}} />);
  expect(await screen.findByText(/モデル別出力/)).toBeTruthy();
});
