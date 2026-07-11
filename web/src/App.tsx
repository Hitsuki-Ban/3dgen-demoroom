import { useEffect, useState } from 'react';
import { ViewerProvider } from './viewer/ViewerContext';
import { MODELS } from './data/models';
import { TASKS } from './data/tasks';
import { useManifest } from './data/useManifest';
import { isRunResult } from './data/types';
import { TaskGallery } from './site/TaskGallery';
import { TaskDetail } from './site/TaskDetail';
import { ModelsOverview } from './site/ModelsOverview';
import { MethodNote } from './site/MethodNote';

const REPO_URL = 'https://github.com/Hitsuki-Ban/3dgen-demoroom';

function Hero() {
  const results = useManifest().entries.filter(isRunResult);
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
        <span className="text-xs px-2.5 py-1 rounded-full bg-sky-900/60 text-sky-200">モデル {doneModels}/{MODELS.length} 実測済み</span>
      </div>
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
    <ViewerProvider>
      <div id="app-content" className="max-w-6xl mx-auto px-4">
        <Hero />
        {selectedTask ? (
          <TaskDetail taskId={selectedTask} onBack={() => selectTask(null)} />
        ) : (
          <>
            <TaskGallery onSelect={selectTask} />
            <ModelsOverview />
            <MethodNote />
          </>
        )}
        <Footer />
      </div>
    </ViewerProvider>
  );
}
