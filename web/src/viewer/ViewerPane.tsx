import { useEffect, useRef, useState, type ReactNode } from 'react';
import type * as THREE from 'three';
import { RegionBlockedError } from './loadModel';
import { useViewer } from './ViewerContext';
import type { PaneStats } from './ViewerCore';

/** これを超えるサイズの GLB は自動ロードせず、サイズを示してクリックロードにする */
const CLICK_TO_LOAD_BYTES = 75 * 2 ** 20;

interface Props {
  title: string;
  /** ペインのロード開始時に一度呼ばれ、表示するモデルを返す(GLB ロードやダミー生成) */
  loadObject: (onProgress?: (fraction: number) => void) => Promise<THREE.Object3D> | THREE.Object3D;
  badge?: string;
  /** 生成時間・VRAM 等の追加表示(フッター2行目) */
  extraInfo?: string;
  /** ヘッダ右端に置く任意 UI(比較チェックボックス等) */
  headerExtra?: ReactNode;
  /** GLB のバイト数(クリックロード判定とサイズ表示に使う) */
  sizeBytes?: number;
  /** GLB ダウンロードリンク(エンジン/DCC での検証用) */
  downloadUrl?: string;
  /** meta.json の内容(モーダル表示用に整形済み文字列) */
  metaJson?: string;
}

export function ViewerPane({
  title,
  loadObject,
  badge,
  extraInfo,
  headerExtra,
  sizeBytes,
  downloadUrl,
  metaJson,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const viewer = useViewer();
  const [stats, setStats] = useState<PaneStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regionBlocked, setRegionBlocked] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [showMeta, setShowMeta] = useState(false);
  /** 画面内に入るまでロードを遅延する(1 課題で数百 MB の一括 DL を避ける) */
  const [visible, setVisible] = useState(false);
  /** 巨大ファイルのクリックロード承諾 */
  const [accepted, setAccepted] = useState(false);

  const needsClick = (sizeBytes ?? 0) > CLICK_TO_LOAD_BYTES;
  const shouldLoad = visible && (!needsClick || accepted);
  const loaded = stats !== null;

  useEffect(() => {
    if (!ref.current || visible) return;
    const el = ref.current;
    // マウント時点でビューポート近傍にあるものは即ロード
    // (IntersectionObserver は非表示タブ等でコールバックが遅延することがあるため、初期判定は同期で行う)
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight + 200 && rect.bottom > -200) {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!viewer || !ref.current || !shouldLoad) return;
    let paneId: number | null = null;
    let cancelled = false;
    (async () => {
      try {
        const object = await loadObject((f) => {
          if (!cancelled) setProgress(f);
        });
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
    // loadObject は初回のみ使う(ペインの同一性は key で管理)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer, shouldLoad]);

  const sizeLabel = sizeBytes !== undefined ? `${(sizeBytes / 2 ** 20).toFixed(1)}MB` : '';

  return (
    <div className="flex flex-col rounded-lg border border-slate-700 overflow-hidden bg-slate-900/40">
      <div className="flex items-center justify-between gap-2 px-3 py-2 text-sm bg-slate-800/80">
        <span className="font-medium truncate">{title}</span>
        <span className="flex items-center gap-2 shrink-0">
          {badge && <span className="text-xs px-2 py-0.5 rounded bg-amber-900/60 text-amber-200">{badge}</span>}
          {headerExtra}
        </span>
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
        <div ref={ref} className="relative aspect-square w-full cursor-grab active:cursor-grabbing touch-none">
          {needsClick && !accepted && (
            <button
              onClick={() => setAccepted(true)}
              className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-slate-300 hover:text-white"
            >
              <span className="text-2xl" aria-hidden>▶</span>
              <span className="text-sm">クリックで読み込み({sizeLabel})</span>
              <span className="text-xs text-slate-500">大きなファイルのため自動読み込みしません</span>
            </button>
          )}
        </div>
      )}
      <div className="px-3 py-1.5 text-xs text-slate-400 bg-slate-800/50">
        <div className="flex items-center justify-between gap-2">
          {regionBlocked ? (
            <span className="text-amber-300/80">地域制限(HTTP 451)</span>
          ) : error ? (
            <span className="text-red-400">load error: {error}</span>
          ) : loaded ? (
            <span>{stats!.triangles.toLocaleString()} tris / {stats!.vertices.toLocaleString()} verts</span>
          ) : shouldLoad ? (
            <span>loading…{progress !== null ? ` ${Math.round(progress * 100)}%` : ''}</span>
          ) : (
            <span className="text-slate-500">{needsClick ? `未読込(${sizeLabel})` : 'スクロールで読み込み'}</span>
          )}
          {(downloadUrl || metaJson) && (
            <span className="flex items-center gap-2 shrink-0">
              {metaJson && (
                <button onClick={() => setShowMeta(true)} className="text-sky-400 hover:underline">
                  meta
                </button>
              )}
              {downloadUrl && (
                <a
                  href={downloadUrl}
                  download
                  title="GLB をダウンロード(利用条件は各モデルのライセンスに従います)"
                  className="text-sky-400 hover:underline"
                >
                  GLB ↓
                </a>
              )}
            </span>
          )}
        </div>
        {extraInfo && !regionBlocked && <div className="text-slate-500 mt-0.5">{extraInfo}</div>}
      </div>
      {showMeta && metaJson && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setShowMeta(false)}
        >
          <div
            className="max-w-lg w-full max-h-[80vh] overflow-auto rounded-lg border border-slate-600 bg-slate-900 p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-2">
              <span className="text-sm font-medium">{title} — meta.json</span>
              <button onClick={() => setShowMeta(false)} className="text-slate-400 hover:text-white text-sm">
                閉じる ✕
              </button>
            </div>
            <pre className="text-xs text-slate-300 whitespace-pre-wrap break-all">{metaJson}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
