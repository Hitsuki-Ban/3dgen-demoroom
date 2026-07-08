import { MODELS } from '../data/models';
import { useManifest } from '../data/useManifest';
import { ModelCard } from './ModelCard';

/** 収録モデル一覧。manifest に結果があるモデルは status を 'done' に昇格して表示する */
export function ModelsOverview() {
  const { results } = useManifest();
  const doneModels = new Set(results.map((r) => r.modelId));

  return (
    <section className="pt-10">
      <h2 className="text-lg font-semibold pb-1">収録モデル({doneModels.size}/{MODELS.length} 実測済み)</h2>
      <p className="text-sm text-slate-400 pb-3">
        選定根拠とライセンス調査は{' '}
        <a
          className="text-sky-400 hover:underline"
          href="https://github.com/Hitsuki-Ban/3dgen-demoroom/blob/main/docs/research/models-merged.md"
          target="_blank"
          rel="noreferrer"
        >
          docs/research/models-merged.md
        </a>{' '}
        を参照。残りのモデルはクラウド GPU で順次実行中です。
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {MODELS.map((m) => (
          <ModelCard key={m.id} model={doneModels.has(m.id) ? { ...m, status: 'done' } : m} />
        ))}
      </div>
    </section>
  );
}
