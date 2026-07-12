import { useEffect, useState } from 'react';
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
  // 情報源は ViewerCore。ローカル state はその写像で、変更通知を購読して常に同期する。
  // ローカル既定値のままだと、グリッド↔比較の遷移でツールバーだけ remount される場面
  // (PR #45 レビュー指摘)や、ハッシュ直遷移で remount されない課題切替の場面で
  // 表示とコア状態が食い違う。
  const [mode, setMode] = useState<DisplayMode>(() => viewer?.getDisplayMode() ?? 'pbr');
  const [sync, setSync] = useState(() => viewer?.getCameraSync() ?? true);
  const [orient, setOrient] = useState(() => viewer?.getOrientationFixEnabled() ?? true);

  useEffect(() => {
    if (!viewer) return;
    const syncFromCore = () => {
      setMode(viewer.getDisplayMode());
      setSync(viewer.getCameraSync());
      setOrient(viewer.getOrientationFixEnabled());
    };
    syncFromCore();
    return viewer.subscribeChange(syncFromCore);
  }, [viewer]);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
      {/* 結合ボタン群だと狭幅でラベルが 1 文字ずつ縦折れ・右端裁切になる(#50)。
          個別チップにして折り返しはボタン単位、ラベルは nowrap で守る */}
      <div className="flex flex-wrap gap-1" role="group" aria-label="表示モード">
        {MODES.map((m) => (
          <button
            key={m.key}
            title={m.hint}
            onClick={() => { setMode(m.key); viewer?.setDisplayMode(m.key); }}
            className={`px-2.5 py-1.5 text-xs sm:text-sm whitespace-nowrap rounded-md border ${
              mode === m.key
                ? 'bg-sky-700 border-sky-600 text-white'
                : 'bg-slate-800 border-slate-600 text-slate-300 hover:bg-slate-700'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-1.5 text-xs sm:text-sm text-slate-300 whitespace-nowrap">
        <input
          type="checkbox"
          checked={sync}
          onChange={(e) => { setSync(e.target.checked); viewer?.setCameraSync(e.target.checked); }}
        />
        カメラ同期
      </label>
      <label
        className="flex items-center gap-1.5 text-xs sm:text-sm text-slate-300 whitespace-nowrap"
        title="OFF にするとモデルが出力した生の向きを表示します(軸慣習の違いも比較対象、という検分用)"
      >
        <input
          type="checkbox"
          checked={orient}
          onChange={(e) => { setOrient(e.target.checked); viewer?.setOrientationFixEnabled(e.target.checked); }}
        />
        向き補正
      </label>
      <button
        onClick={() => viewer?.resetCameras()}
        className="px-2.5 py-1.5 text-xs sm:text-sm whitespace-nowrap rounded-md border border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700"
      >
        視点リセット
      </button>
    </div>
  );
}
