import { useState } from 'react';
import { useViewer } from '../viewer/ViewerContext';
import type { DisplayMode } from '../viewer/ViewerCore';

const MODES: { key: DisplayMode; label: string }[] = [
  { key: 'pbr', label: 'PBR' },
  { key: 'wireframe', label: 'Wireframe' },
  { key: 'matcap', label: 'Matcap' },
  { key: 'normal', label: 'Normal' },
  { key: 'uv', label: 'UV Checker' },
];

export function ViewerToolbar() {
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
