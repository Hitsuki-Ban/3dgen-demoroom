import { useState } from 'react';
import { ViewerProvider, useViewer } from './viewer/ViewerContext';
import { ViewerPane } from './viewer/ViewerPane';
import { DUMMY_MODELS } from './demo/dummyModels';
import type { DisplayMode } from './viewer/ViewerCore';

const MODES: { key: DisplayMode; label: string }[] = [
  { key: 'pbr', label: 'PBR' },
  { key: 'wireframe', label: 'Wireframe' },
  { key: 'matcap', label: 'Matcap' },
  { key: 'normal', label: 'Normal' },
  { key: 'uv', label: 'UV Checker' },
];

function Toolbar() {
  const viewer = useViewer();
  const [mode, setMode] = useState<DisplayMode>('pbr');
  const [sync, setSync] = useState(true);

  return (
    <div className="flex flex-wrap items-center gap-2 py-3">
      <div className="flex rounded-md overflow-hidden border border-slate-600">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => { setMode(m.key); viewer?.setDisplayMode(m.key); }}
            className={`px-3 py-1.5 text-sm ${mode === m.key ? 'bg-sky-700 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-1.5 text-sm text-slate-300 ml-2">
        <input
          type="checkbox"
          checked={sync}
          onChange={(e) => { setSync(e.target.checked); viewer?.setCameraSync(e.target.checked); }}
        />
        カメラ同期
      </label>
      <button
        onClick={() => viewer?.resetCameras()}
        className="px-3 py-1.5 text-sm rounded-md border border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700"
      >
        視点リセット
      </button>
    </div>
  );
}

export default function App() {
  return (
    <ViewerProvider>
      <div id="app-content" className="max-w-6xl mx-auto px-4 pb-16">
        <header className="pt-8 pb-2">
          <h1 className="text-2xl font-bold">3DGen DemoRoom</h1>
          <p className="text-slate-400 text-sm mt-1">
            オープンソース 3D 生成モデルの横並び比較(開発用ダミー表示中 — ベンチ成果物の GLB が入り次第差し替わります)
          </p>
        </header>
        <Toolbar />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {DUMMY_MODELS.map((m) => (
            <ViewerPane key={m.name} title={m.name} badge={m.badge} loadObject={m.build} />
          ))}
        </div>
      </div>
    </ViewerProvider>
  );
}
