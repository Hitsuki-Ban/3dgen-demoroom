import { TASKS } from '../data/tasks';
import type { TaskInfo } from '../data/types';

function Stars({ n }: { n: number }) {
  return <span className="text-amber-400">{'★'.repeat(n)}</span>;
}

function TaskCard({ task, onSelect }: { task: TaskInfo; onSelect: (id: string) => void }) {
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
        <div className="text-xs text-slate-400 mt-0.5">{task.category}</div>
      </div>
    </button>
  );
}

export function TaskGallery({ onSelect }: { onSelect: (id: string) => void }) {
  return (
    <section>
      <h2 className="text-lg font-semibold pt-6 pb-3">ベンチマーク課題(20)</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {TASKS.map((t) => (
          <TaskCard key={t.id} task={t} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
