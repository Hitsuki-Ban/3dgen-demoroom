import { useState } from 'react';
import { useViewer } from '../viewer/ViewerContext';
import type { DisplayMode } from '../viewer/ViewerCore';

const MODES: { key: DisplayMode; label: string; hint: string }[] = [
  { key: 'pbr', label: 'PBR', hint: 'モデルが出力したマテリアルそのまま' },
  { key: 'toon', label: 'トゥーン+輪郭', hint: 'セルシェーディング+輪郭線でシルエットと面の流れを見る' },
  { key: 'matcap', label: 'Matcap', hint: 'クレイ調で形状のみを見る' },
  { key: 'wireframe', label: 'Wireframe', hint: 'ポリゴン割りを見る' },
  { key: 'normal', label: 'Normal', hint: '法線の乱れを色で見る' },
  { key: 'uv', label: 'UV', hint: 'UV 展開の歪みをチェッカーで見る' },
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
            title={m.hint}
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
