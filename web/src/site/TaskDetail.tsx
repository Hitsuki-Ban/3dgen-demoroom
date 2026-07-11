import { useEffect, useState } from 'react';
import { MODELS } from '../data/models';
import { TASKS } from '../data/tasks';
import { useManifest } from '../data/useManifest';
import type { ModelInfo, RunResult } from '../data/types';
import { loadModel } from '../viewer/loadModel';
import { useViewer } from '../viewer/ViewerContext';
import { ViewerPane } from '../viewer/ViewerPane';
import { ModelCard } from './ModelCard';
import { ViewerToolbar } from './ViewerToolbar';

function formatResultInfo(wallClock: number, peakVram: number, sizeBytes: number, gpu: string): string {
  return `${wallClock.toFixed(1)}s / VRAM ${(peakVram / 2 ** 30).toFixed(1)}GB / ${(sizeBytes / 2 ** 20).toFixed(1)}MB / ${gpu}`;
}

function paneBadge(m: ModelInfo): string | undefined {
  if (m.badges.includes('geometry-only')) return 'geometry-only';
  if (m.badges.includes('geo-restricted')) return '地域制限';
  return undefined;
}

function makeLoadObject(m: ModelInfo, result: RunResult) {
  return async () => {
    const object = await loadModel(result.glbUrl);
    const fix = m.orientationFix;
    if (fix) {
      const d = Math.PI / 180;
      object.rotation.set((fix.x ?? 0) * d, (fix.y ?? 0) * d, (fix.z ?? 0) * d);
    }
    return object;
  };
}

export function TaskDetail({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const task = TASKS.find((t) => t.id === taskId);
  const { results } = useManifest();
  const viewer = useViewer();
  /** 大画面比較に選択中のモデル id(最大 2 つ。3 つ目を選ぶと古い方から入れ替え) */
  const [compareSel, setCompareSel] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);

  // 課題を開くたびに表示状態を既定へ戻す(ViewerCore の mode はペインより長生きするため、
  // 前の課題で選んだ matcap 等が新しいペインへ引き継がれて UI 表示と食い違うのを防ぐ)
  useEffect(() => {
    viewer?.setDisplayMode('pbr');
    viewer?.setCameraSync(true);
    setCompareSel([]);
    setComparing(false);
  }, [viewer, taskId]);

  if (!task) return null;

  const resultByModel = new Map(results.filter((r) => r.taskId === taskId).map((r) => [r.modelId, r]));
  const doneCount = resultByModel.size;

  const toggleCompare = (id: string) =>
    setCompareSel((sel) =>
      sel.includes(id) ? sel.filter((x) => x !== id) : sel.length >= 2 ? [sel[1], id] : [...sel, id],
    );

  const compareModels = compareSel
    .map((id) => MODELS.find((m) => m.id === id))
    .filter((m): m is ModelInfo => !!m && resultByModel.has(m.id));

  return (
    <section className="pt-6">
      <button onClick={onBack} className="text-sm text-sky-400 hover:underline">
        ← 課題一覧に戻る
      </button>
      <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6 mt-4">
        {/* リファレンスをスクロール中も見えるよう固定(比較の基準を常時提示) */}
        <div className="self-start lg:sticky lg:top-4">
          <img src={task.referenceImage} alt={task.id} className="w-full rounded-lg border border-slate-700" />
          <h2 className="text-lg font-semibold mt-3">{task.id}</h2>
          <div className="text-xs text-slate-400 mt-1">
            {task.category} / 難易度 <span className="text-amber-400">{'★'.repeat(task.difficulty)}</span>
          </div>
          <p className="text-sm text-slate-300 mt-3 leading-relaxed">{task.prompt}</p>
          <div className="mt-3 rounded-md bg-slate-800/60 px-3 py-2">
            <div className="text-xs font-medium text-slate-300">検証ポイント</div>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">{task.probe}</p>
          </div>
        </div>
        <div>
          {comparing && compareModels.length === 2 ? (
            <>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-300">
                  {compareModels[0].name} vs {compareModels[1].name}
                </h3>
                <button
                  onClick={() => setComparing(false)}
                  className="text-sm text-sky-400 hover:underline"
                >
                  ← 全モデル表示に戻る
                </button>
              </div>
              <ViewerToolbar />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {compareModels.map((m) => {
                  const result = resultByModel.get(m.id)!;
                  return (
                    <ViewerPane
                      key={`cmp:${taskId}:${m.id}`}
                      title={m.name}
                      badge={paneBadge(m)}
                      loadObject={makeLoadObject(m, result)}
                      extraInfo={formatResultInfo(
                        result.meta.wall_clock_seconds,
                        result.meta.peak_vram_bytes,
                        result.glbSizeBytes,
                        result.meta.gpu_name,
                      )}
                    />
                  );
                })}
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-slate-300">
                  モデル別出力({doneCount}/{MODELS.length} 完了)
                </h3>
                {compareSel.length === 2 && (
                  <button
                    onClick={() => setComparing(true)}
                    className="text-sm px-3 py-1.5 rounded-md bg-sky-700 text-white hover:bg-sky-600"
                  >
                    選択した 2 モデルを大きく比較
                  </button>
                )}
              </div>
              {doneCount > 0 && <ViewerToolbar />}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {MODELS.map((m) => {
                  const result = resultByModel.get(m.id);
                  if (!result) return <ModelCard key={m.id} model={m} />;
                  return (
                    <ViewerPane
                      // taskId を key に含めて課題切替時に必ず remount する
                      // (同一 key の再利用だと GLB ロード effect が走らず前の課題のモデルが残る)
                      key={`${taskId}:${m.id}`}
                      title={m.name}
                      badge={paneBadge(m)}
                      headerExtra={
                        <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={compareSel.includes(m.id)}
                            onChange={() => toggleCompare(m.id)}
                          />
                          比較
                        </label>
                      }
                      loadObject={makeLoadObject(m, result)}
                      extraInfo={formatResultInfo(
                        result.meta.wall_clock_seconds,
                        result.meta.peak_vram_bytes,
                        result.glbSizeBytes,
                        result.meta.gpu_name,
                      )}
                    />
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
