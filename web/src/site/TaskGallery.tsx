import { MODELS } from '../data/models';
import { TASKS } from '../data/tasks';
import { useManifest } from '../data/useManifest';
import type { TaskInfo } from '../data/types';

function Stars({ n }: { n: number }) {
  return <span className="text-amber-400">{'★'.repeat(n)}</span>;
}

function TaskCard({
  task,
  resultCount,
  onSelect,
}: {
  task: TaskInfo;
  resultCount: number;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(task.id)}
      className="text-left rounded-lg border border-slate-700 overflow-hidden bg-slate-900/40 hover:border-sky-600 transition-colors"
    >
      <img src={task.referenceImage} alt={task.id} loading="lazy" className="w-full aspect-square object-cover" />
      <div className="px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium truncate">{task.id}</span>
          <Stars n={task.difficulty} />
        </div>
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <span className="text-xs text-slate-400">{task.category}</span>
          {resultCount > 0 && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-sky-900/60 text-sky-200">
              {resultCount}/{MODELS.length}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

export function TaskGallery({ onSelect }: { onSelect: (id: string) => void }) {
  const { results } = useManifest();
  const countByTask = new Map<string, number>();
  for (const r of results) countByTask.set(r.taskId, (countByTask.get(r.taskId) ?? 0) + 1);

  return (
    <section>
      <h2 className="text-lg font-semibold pt-8 pb-1">ベンチマーク課題({TASKS.length})</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {TASKS.map((t) => (
          <TaskCard key={t.id} task={t} resultCount={countByTask.get(t.id) ?? 0} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
