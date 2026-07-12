import { render, waitFor } from '@testing-library/react';
import { Group } from 'three';
import { beforeEach, expect, it, vi } from 'vitest';
import { MODELS } from '../data/models';
import { resolveOrientationFix } from '../data/orientationFixes';
import { TASKS } from '../data/tasks';
import type { SiteManifest } from '../data/types';

vi.mock('../viewer/ViewerCore', () => import('../test/viewer-core-stub'));
// GLB 取得は本物を使えないため、ロード成功だけを模して addPane までの配線を検証する
vi.mock('../viewer/loadModel', () => ({
  loadModel: async () => new Group(),
  disposeObject: () => {},
  RegionBlockedError: class RegionBlockedError extends Error {},
}));

import { ViewerCore } from '../test/viewer-core-stub';
import { TaskDetail } from './TaskDetail';

// #85: セル単位の absolute viewing 回転が model 既定 fix を「置き換えて」addPane に届くこと。

const manifest: SiteManifest = {
  generatedAt: '2026-07-12T00:00:00Z',
  partial: true,
  entries: [
    {
      status: 'success',
      taskId: 'cartoon-apple',
      modelId: 'sf3d',
      glbUrl: '/run-assets/sf3d/cartoon-apple/output.glb',
      glbSizeBytes: 1024,
      metrics: { wallClockSeconds: 10, peakVramBytes: 2 ** 30, gpuName: 'TEST GPU' },
      meta: {},
    },
  ],
};

beforeEach(() => {
  ViewerCore.instances.length = 0;
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

it('registry は全 11×25 セルを網羅し、fixed セルは有限な絶対回転を持つ', () => {
  for (const model of MODELS) {
    for (const task of TASKS) {
      const fix = resolveOrientationFix(model.id, task.id);
      // excluded セル(partcrafter/chrome-espresso-machine)は model 既定(なし)へフォールバック
      if (model.id === 'partcrafter' && task.id === 'chrome-espresso-machine') {
        expect(fix).toBeUndefined();
        continue;
      }
      expect(fix, `${model.id}/${task.id}`).toBeDefined();
      for (const v of Object.values(fix!)) expect(Number.isFinite(v)).toBe(true);
    }
  }
});

it('cell の absolute 回転は model 既定 fix を置き換える(加算しない)', () => {
  // sf3d の model 既定は y:180 だが、cell 値は絶対値としてそれを置換する
  const fix = resolveOrientationFix('sf3d', 'cartoon-apple');
  expect(fix).toEqual({ x: 0, y: -90, z: 0 });
});

it('解決された回転が ViewerCore.addPane まで届く', async () => {
  render(<TaskDetail taskId="cartoon-apple" onBack={() => {}} />);
  await waitFor(() => {
    const core = ViewerCore.instances.at(-1);
    expect(core?.addPaneCalls.length).toBeGreaterThan(0);
  });
  const core = ViewerCore.instances.at(-1)!;
  expect(core.addPaneCalls[0].fix).toEqual({ x: 0, y: -90, z: 0 });
});
