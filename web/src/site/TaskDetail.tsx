import { MODELS } from '../data/models';
import { TASKS } from '../data/tasks';
import { ModelCard } from './ModelCard';

export function TaskDetail({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const task = TASKS.find((t) => t.id === taskId);
  if (!task) return null;

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
          <h3 className="text-sm font-semibold text-slate-300 pb-2">
            モデル別出力(ベンチ実行後、ここが 3D ビューアの横並びになります)
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {MODELS.map((m) => (
              <ModelCard key={m.id} model={m} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
