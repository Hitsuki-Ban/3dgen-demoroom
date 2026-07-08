import { useEffect, useRef, useState } from 'react';
import type * as THREE from 'three';
import { RegionBlockedError } from './loadModel';
import { useViewer } from './ViewerContext';
import type { PaneStats } from './ViewerCore';

interface Props {
  title: string;
  /** ペイン mount 時に一度呼ばれ、表示するモデルを返す(GLB ロードやダミー生成) */
  loadObject: () => Promise<THREE.Object3D> | THREE.Object3D;
  badge?: string;
  /** 生成時間・VRAM 等の追加表示(フッター2行目) */
  extraInfo?: string;
}

export function ViewerPane({ title, loadObject, badge, extraInfo }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const viewer = useViewer();
  const [stats, setStats] = useState<PaneStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regionBlocked, setRegionBlocked] = useState(false);

  useEffect(() => {
    if (!viewer || !ref.current) return;
    let paneId: number | null = null;
    let cancelled = false;
    (async () => {
      try {
        const object = await loadObject();
        if (cancelled) return;
        paneId = viewer.addPane(ref.current!, object);
        setStats(viewer.getStats(paneId));
      } catch (e) {
        if (e instanceof RegionBlockedError) setRegionBlocked(true);
        else setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (paneId !== null) viewer.removePane(paneId);
    };
    // loadObject は初回のみ使う(ペインの同一性は title で管理)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer]);

  return (
    <div className="flex flex-col rounded-lg border border-slate-700 overflow-hidden bg-slate-900/40">
      <div className="flex items-center justify-between px-3 py-2 text-sm bg-slate-800/80">
        <span className="font-medium">{title}</span>
        {badge && <span className="text-xs px-2 py-0.5 rounded bg-amber-900/60 text-amber-200">{badge}</span>}
      </div>
      {regionBlocked ? (
        <div className="aspect-square w-full flex flex-col items-center justify-center gap-2 px-6 text-center">
          <span className="text-2xl" aria-hidden>🌐</span>
          <p className="text-sm text-amber-200">ライセンス条項により、この地域では表示できません</p>
          <p className="text-xs text-slate-400 leading-relaxed">
            Tencent Hunyuan3D 2.1 Community License 5(c) は、EU・英国・韓国での生成物の表示・使用を許諾していません。
          </p>
        </div>
      ) : (
        <div ref={ref} className="aspect-square w-full cursor-grab active:cursor-grabbing touch-none" />
      )}
      <div className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/50">
        {regionBlocked
          ? <span className="text-amber-300/80">地域制限(HTTP 451)</span>
          : error
            ? <span className="text-red-400">load error: {error}</span>
            : stats
              ? <span>{stats.triangles.toLocaleString()} tris / {stats.vertices.toLocaleString()} verts</span>
              : 'loading…'}
        {extraInfo && !regionBlocked && <div className="text-slate-500 mt-0.5">{extraInfo}</div>}
      </div>
    </div>
  );
}
