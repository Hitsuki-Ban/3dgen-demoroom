import { ViewerPane } from '../viewer/ViewerPane';
import { DUMMY_MODELS } from '../demo/dummyModels';
import { ViewerToolbar } from './ViewerToolbar';

/** ベンチ成果物が届くまでのビューア動作デモ(ダミーモデル) */
export function ViewerDemo() {
  return (
    <section className="pt-10">
      <h2 className="text-lg font-semibold">ビューアデモ(開発用ダミー)</h2>
      <p className="text-sm text-slate-400 mt-1">
        単一 canvas マルチビューポート・カメラ同期・検分モードの動作確認用。ベンチ成果物の GLB が入り次第、課題ページに統合されます。
      </p>
      <ViewerToolbar />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {DUMMY_MODELS.map((m) => (
          <ViewerPane key={m.name} title={m.name} badge={m.badge} loadObject={m.build} />
        ))}
      </div>
    </section>
  );
}
