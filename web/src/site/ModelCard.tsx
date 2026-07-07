import { BADGE_LABELS } from '../data/models';
import type { ModelInfo } from '../data/types';

const STATUS_LABELS: Record<ModelInfo['status'], string> = {
  planned: 'ベンチ待機中',
  running: '実行中',
  done: '完了',
  excluded: '除外',
};

export function ModelCard({ model }: { model: ModelInfo }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2.5 flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-sm font-medium">{model.name}</span>
          <span className="text-xs text-slate-500 ml-2">{model.org}</span>
        </div>
        <span className="text-xs text-slate-400">{STATUS_LABELS[model.status]}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs px-2 py-0.5 rounded bg-emerald-900/60 text-emerald-200">{model.license.name}</span>
        {model.badges.map((b) => (
          <span key={b} className={`text-xs px-2 py-0.5 rounded ${BADGE_LABELS[b].className}`}>
            {BADGE_LABELS[b].label}
          </span>
        ))}
      </div>
      {model.license.note && <p className="text-xs text-slate-500">{model.license.note}</p>}
      {model.vramNote && <p className="text-xs text-slate-500">VRAM: {model.vramNote}</p>}
    </div>
  );
}
