import { Suspense, lazy, useEffect, useState } from 'react';
import { MODELS } from './data/models';
import { TASKS } from './data/tasks';
import { useManifest } from './data/useManifest';
import { isRunResult } from './data/types';
import { TaskGallery } from './site/TaskGallery';
import { ModelsOverview } from './site/ModelsOverview';
import { MethodNote } from './site/MethodNote';

// Viewer(three.js 一式)は課題詳細でしか使わないため別チャンクへ分離する(#59)。
// homepage では WebGL context / canvas / RAF を一切作らない
const TaskDetail = lazy(() => import('./site/TaskDetail').then((m) => ({ default: m.TaskDetail })));

const REPO_URL = 'https://github.com/Hitsuki-Ban/3dgen-demoroom';

function Hero() {
  const { status, manifest, retry } = useManifest();
  const results = manifest.entries.filter(isRunResult);
  const doneModels = new Set(results.map((r) => r.modelId)).size;

  return (
    <header className="pt-10 pb-2">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">3DGen DemoRoom</h1>
          <p className="text-slate-400 mt-2 max-w-2xl leading-relaxed">
            オープンソースの 3D 生成モデル {MODELS.length} 種を同一課題・公式デフォルト・無修正で比較する展示室。
          </p>
        </div>
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 text-sm px-3 py-1.5 rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800"
        >
          GitHub
        </a>
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <span className="text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-300">{TASKS.length} 課題</span>
        {status === 'loading' ? (
          <span className="text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-400">実測データ読み込み中…</span>
        ) : status === 'ready' ? (
          <span className="text-xs px-2.5 py-1 rounded-full bg-sky-900/60 text-sky-200">モデル {doneModels}/{MODELS.length} 実測済み</span>
        ) : null}
      </div>
      {/* fetch 失敗を「0/11」という誤った正常表示にせず、明示バナー+再試行を出す(#54) */}
      {status === 'error' && (
        <div
          role="alert"
          className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-200"
        >
          <span>実測データ(manifest)の読み込みに失敗しました。ネットワークを確認してください。</span>
          <button
            onClick={retry}
            className="px-2.5 py-1 rounded-md border border-red-700 text-red-100 text-xs hover:bg-red-900/50"
          >
            再試行
          </button>
        </div>
      )}
    </header>
  );
}

function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-800 pt-6 pb-10 text-xs text-slate-500 leading-relaxed">
      <p>
        掲載の 3D モデルはすべて AI 生成物(入力画像も AI 生成)。各モデルのライセンス・地域制限は「収録モデル」を参照。
        手順・実行コード・調査記録:{' '}
        <a className="text-sky-500 hover:underline" href={REPO_URL} target="_blank" rel="noreferrer">
          {REPO_URL.replace('https://', '')}
        </a>
      </p>
    </footer>
  );
}

/** URL ハッシュ(#t=<taskId>)から選択課題を読む。課題の共有リンクを可能にする */
function taskFromHash(): string | null {
  const id = new URLSearchParams(window.location.hash.slice(1)).get('t');
  return id && TASKS.some((t) => t.id === id) ? id : null;
}

export default function App() {
  const [selectedTask, setSelectedTask] = useState<string | null>(() => taskFromHash());

  useEffect(() => {
    const onHashChange = () => {
      setSelectedTask(taskFromHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  // 選択は URL ハッシュ経由で一元化(hashchange → state 同期。ブラウザの戻る/進むも効く)
  const selectTask = (id: string | null) => {
    window.location.hash = id ? `t=${id}` : '';
  };

  return (
    <div id="app-content" className="max-w-6xl mx-auto px-4">
      <Hero />
      {selectedTask ? (
        <Suspense fallback={<p className="pt-10 text-sm text-slate-400">ビューアを読み込み中…</p>}>
          <TaskDetail taskId={selectedTask} onBack={() => selectTask(null)} />
        </Suspense>
      ) : (
        <>
          <TaskGallery onSelect={selectTask} />
          <ModelsOverview />
          <MethodNote />
        </>
      )}
      <Footer />
    </div>
  );
}
