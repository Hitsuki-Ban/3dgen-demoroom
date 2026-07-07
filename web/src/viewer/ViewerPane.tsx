import { useEffect, useRef, useState } from 'react';
import type * as THREE from 'three';
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
        setError(e instanceof Error ? e.message : String(e));
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
      <div ref={ref} className="aspect-square w-full cursor-grab active:cursor-grabbing touch-none" />
      <div className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/50">
        {error
          ? <span className="text-red-400">load error: {error}</span>
          : stats
            ? <span>{stats.triangles.toLocaleString()} tris / {stats.vertices.toLocaleString()} verts</span>
            : 'loading…'}
        {extraInfo && <div className="text-slate-500 mt-0.5">{extraInfo}</div>}
      </div>
    </div>
  );
}
