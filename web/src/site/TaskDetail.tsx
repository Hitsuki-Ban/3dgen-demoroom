import { useEffect, useId, useState } from 'react';
import { MODELS } from '../data/models';
import { TASKS } from '../data/tasks';
import { useManifest } from '../data/useManifest';
import { resolveOrientationFix } from '../data/orientationFixes';
import { isRunResult, type ModelInfo, type RunFailure, type RunResult, type TaskInfo } from '../data/types';
import { parseVramMeasurement, vramScopeInfo } from '../data/vramScope';
import { loadModel } from '../viewer/loadModel';
import { ViewerProvider, useViewer } from '../viewer/ViewerContext';
import { ViewerPane } from '../viewer/ViewerPane';
import { ModelCard, ModelFailureCard } from './ModelCard';
import { ViewerToolbar } from './ViewerToolbar';

/** フッター 2 行目の実測サマリ。VRAM 値の後ろの小さな「!」マークに hover/focus で
 *  計測口径の説明を出す(#72)。ラベルのインライン常時表示はしない(オーナー UX FB:
 *  値の見た目を汚さず、気になった人だけ読めればよい)。tooltip は native title でなく
 *  focusable 要素+role=tooltip — キーボード・タッチ・支援技術からも到達可能(PR #82) */
function ResultInfo({ result }: { result: RunResult }) {
  const { wallClockSeconds, peakVramBytes, gpuName } = result.metrics;
  const scope = vramScopeInfo(parseVramMeasurement(result.meta));
  const hintId = useId();
  return (
    <>
      {wallClockSeconds.toFixed(1)}s / VRAM {(peakVramBytes / 2 ** 30).toFixed(1)}GB
      <span
        tabIndex={0}
        aria-label="VRAM 計測口径の注記"
        aria-describedby={hintId}
        className={`group relative ml-0.5 inline-flex h-3.5 w-3.5 cursor-help select-none items-center justify-center rounded-full border text-[10px] leading-none align-text-top focus:outline-none focus-visible:ring-1 focus-visible:ring-sky-500 ${
          scope.attention
            ? 'border-red-700 text-red-300'
            : 'border-slate-600 text-slate-500 hover:text-slate-300'
        }`}
      >
        !
        <span
          id={hintId}
          role="tooltip"
          className="invisible group-hover:visible group-focus-within:visible pointer-events-none absolute left-0 bottom-full mb-1 z-10 w-56 rounded-md border border-slate-600 bg-slate-900 px-2.5 py-1.5 text-xs leading-relaxed text-slate-300 whitespace-normal text-left"
        >
          <span className="font-medium">{scope.label}</span> — {scope.hint}
        </span>
      </span>{' '}
      / {(result.glbSizeBytes / 2 ** 20).toFixed(1)}MB / {gpuName}
    </>
  );
}

function paneBadge(m: ModelInfo): string | undefined {
  if (m.badges.includes('geometry-only')) return 'geometry-only';
  if (m.badges.includes('geo-restricted')) return '地域制限';
  return undefined;
}

function makeLoadObject(result: RunResult) {
  return (onProgress?: (fraction: number) => void, signal?: AbortSignal) =>
    loadModel(result.glbUrl, onProgress, signal);
}

/** 表示状態: 全モデルグリッド / 2 モデル比較 / 単体フォーカス */
type ViewState = { type: 'grid' } | { type: 'compare' } | { type: 'focus'; modelId: string };

/** 大画面モード(比較・フォーカス)で使う共通ペイン */
function ResultPane({
  m,
  result,
  task,
  large,
  keyPrefix,
  taskId,
  headerExtra,
}: {
  m: ModelInfo;
  result: RunResult;
  task: TaskInfo;
  large?: boolean;
  keyPrefix: string;
  taskId: string;
  headerExtra?: React.ReactNode;
}) {
  return (
    <ViewerPane
      key={`${keyPrefix}:${taskId}:${m.id}`}
      title={m.name}
      badge={paneBadge(m)}
      large={large}
      headerExtra={headerExtra}
      sizeBytes={result.glbSizeBytes}
      downloadUrl={result.glbUrl}
      metaJson={JSON.stringify(result.meta, null, 2)}
      // セル単位の absolute viewing 回転(#85)。cell が model 既定 fix を置き換える(加算しない)
      orientationFix={resolveOrientationFix(m.id, taskId)}
      // 未ロード/クリックロードのプレビューは、このモデル自身の出力サムネイル(#66/#73)を優先。
      // 古い manifest や失敗直後の再発行などで thumbUrl が無いセルはリファレンス画像に落とす
      previewImage={result.thumbUrl ?? task.referenceImage}
      loadObject={makeLoadObject(result)}
      extraInfo={<ResultInfo result={result} />}
    />
  );
}

/** ViewerProvider(共有 canvas + ViewerCore)は課題詳細のスコープでだけ生成し、
 *  一覧へ戻ったら unmount で dispose する(#59)。課題切替では remount しない */
export function TaskDetail(props: { taskId: string; onBack: () => void }) {
  return (
    <ViewerProvider>
      <TaskDetailInner {...props} />
    </ViewerProvider>
  );
}

function TaskDetailInner({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const task = TASKS.find((t) => t.id === taskId);
  const { status: manifestStatus, manifest } = useManifest();
  const viewer = useViewer();
  /** 大画面比較に選択中のモデル id(最大 2 つ。3 つ目を選ぶと古い方から入れ替え) */
  const [compareSel, setCompareSel] = useState<string[]>([]);
  const [view, setView] = useState<ViewState>({ type: 'grid' });

  // 課題を開くたびに表示状態を既定へ戻す(ViewerCore の mode はペインより長生きするため、
  // 前の課題で選んだ matcap 等が新しいペインへ引き継がれて UI 表示と食い違うのを防ぐ)
  useEffect(() => {
    viewer?.setDisplayMode('pbr');
    viewer?.setCameraSync(true);
    setCompareSel([]);
    setView({ type: 'grid' });
  }, [viewer, taskId]);

  if (!task) return null;

  // success / failure を分けて持つ: failure は「ベンチ待機中」ではなく「生成失敗」として表示する(#54)
  const taskEntries = manifest.entries.filter((e) => e.taskId === taskId);
  const resultByModel = new Map(taskEntries.filter(isRunResult).map((r) => [r.modelId, r]));
  const failureByModel = new Map(
    taskEntries.filter((e): e is RunFailure => !isRunResult(e)).map((e) => [e.modelId, e]),
  );
  const doneCount = resultByModel.size;

  const toggleCompare = (id: string) =>
    setCompareSel((sel) =>
      sel.includes(id) ? sel.filter((x) => x !== id) : sel.length >= 2 ? [sel[1], id] : [...sel, id],
    );

  const compareModels = compareSel
    .map((id) => MODELS.find((m) => m.id === id))
    .filter((m): m is ModelInfo => !!m && resultByModel.has(m.id));

  // hash での課題切替直後は reset effect より先に旧 view のまま再描画される。
  // 新課題にフォーカス対象の result が無い(部分 manifest・failure セル)場合は
  // グリッド表示へフォールバックする(compare 側の resultByModel.has フィルタと同等の guard)
  const focusModel =
    view.type === 'focus' && resultByModel.has(view.modelId)
      ? MODELS.find((m) => m.id === view.modelId)
      : undefined;

  // 大画面モード(比較 / フォーカス)はリファレンス列を畳んでフル幅を使う
  if ((view.type === 'compare' && compareModels.length === 2) || (view.type === 'focus' && focusModel)) {
    const largeModels = view.type === 'focus' ? [focusModel!] : compareModels;
    return (
      <section className="pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={() => setView({ type: 'grid' })} className="text-sm text-sky-400 hover:underline">
            ← 全モデル表示に戻る
          </button>
          <h3 className="text-sm font-semibold text-slate-300">
            {task.id} — {largeModels.map((m) => m.name).join(' vs ')}
          </h3>
          {/* 比較の基準としてリファレンスを小さく添える */}
          <img
            src={task.referenceImage}
            alt={`${task.id} リファレンス画像`}
            className="w-14 h-14 rounded border border-slate-700 object-cover ml-auto"
          />
        </div>
        <ViewerToolbar />
        <div className={`grid grid-cols-1 gap-4 ${largeModels.length === 2 ? 'md:grid-cols-2' : ''}`}>
          {largeModels.map((m) => (
            <ResultPane
              key={`large:${taskId}:${m.id}`}
              m={m}
              result={resultByModel.get(m.id)!}
              task={task}
              large
              keyPrefix="large"
              taskId={taskId}
            />
          ))}
        </div>
      </section>
    );
  }

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
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-300">
              モデル別出力(
              {manifestStatus === 'loading' && doneCount === 0
                ? '実測データ読み込み中…'
                : `${doneCount}/${MODELS.length} 完了`}
              )
            </h3>
            {compareSel.length === 2 && (
              <button
                onClick={() => setView({ type: 'compare' })}
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
              if (!result) {
                const failed = failureByModel.get(m.id);
                if (failed) return <ModelFailureCard key={m.id} model={m} failure={failed.failure} />;
                return <ModelCard key={m.id} model={m} />;
              }
              return (
                <ResultPane
                  // taskId を key に含めて課題切替時に必ず remount する
                  // (同一 key の再利用だと GLB ロード effect が走らず前の課題のモデルが残る)
                  key={`grid:${taskId}:${m.id}`}
                  m={m}
                  result={result}
                  task={task}
                  keyPrefix="grid"
                  taskId={taskId}
                  headerExtra={
                    <>
                      <label className="flex items-center gap-1 text-xs text-slate-400 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={compareSel.includes(m.id)}
                          onChange={() => toggleCompare(m.id)}
                        />
                        比較
                      </label>
                      <button
                        onClick={() => setView({ type: 'focus', modelId: m.id })}
                        title="このモデルを単体で大きく表示"
                        className="text-slate-400 hover:text-white text-sm leading-none"
                      >
                        ⛶
                      </button>
                    </>
                  }
                />
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
