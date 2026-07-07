import { MODELS } from '../data/models';
import { TASKS } from '../data/tasks';
import { useManifest } from '../data/useManifest';
import { loadModel } from '../viewer/loadModel';
import { ViewerPane } from '../viewer/ViewerPane';
import { ModelCard } from './ModelCard';
import { ViewerToolbar } from './ViewerToolbar';

function formatResultInfo(wallClock: number, peakVram: number, sizeBytes: number, gpu: string): string {
  return `${wallClock.toFixed(1)}s / VRAM ${(peakVram / 2 ** 30).toFixed(1)}GB / ${(sizeBytes / 2 ** 20).toFixed(1)}MB / ${gpu}`;
}

export function TaskDetail({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const task = TASKS.find((t) => t.id === taskId);
  const { results } = useManifest();
  if (!task) return null;

  const resultByModel = new Map(results.filter((r) => r.taskId === taskId).map((r) => [r.modelId, r]));
  const doneCount = resultByModel.size;

  return (
    <section className="pt-6">
      <button onClick={onBack} className="text-sm text-sky-400 hover:underline">
        ← 課題一覧に戻る
      </button>
      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6 mt-4">
        <div>
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
          <h3 className="text-sm font-semibold text-slate-300">
            モデル別出力({doneCount}/{MODELS.length} 完了)
          </h3>
          {doneCount > 0 && <ViewerToolbar />}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {MODELS.map((m) => {
              const result = resultByModel.get(m.id);
              if (!result) return <ModelCard key={m.id} model={m} />;
              return (
                <ViewerPane
                  key={m.id}
                  title={m.name}
                  badge={m.badges.includes('geometry-only') ? 'geometry-only' : undefined}
                  loadObject={() => loadModel(result.glbUrl)}
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
        </div>
      </div>
    </section>
  );
}
