import { useSyncExternalStore } from 'react';
import type { SiteManifest } from './types';

const EMPTY: SiteManifest = { generatedAt: '', partial: false, entries: [] };

export type ManifestStatus = 'loading' | 'ready' | 'error';

export interface ManifestState {
  status: ManifestStatus;
  manifest: SiteManifest;
  /** error 時にユーザー操作で再取得する。同一 SPA セッション内で復帰できる(#54) */
  retry: () => void;
}

// 全消費者(Hero / TaskGallery / TaskDetail)で 1 つの fetch を共有する module store。
// 以前は fetch 失敗を空 manifest に置き換えて cache していたため、エラーが
// 「モデル 0/11」という誤った正常表示になり、再試行もできなかった(#54)。
let state: { status: ManifestStatus; manifest: SiteManifest } = { status: 'loading', manifest: EMPTY };
let inflight = false;
let started = false;
const listeners = new Set<() => void>();

function notify() {
  for (const l of listeners) l();
}

function load() {
  if (inflight || state.status === 'ready') return;
  inflight = true;
  if (state.status !== 'loading') {
    state = { ...state, status: 'loading' };
    notify();
  }
  fetch('/manifest.json')
    .then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const manifest = (await r.json()) as SiteManifest;
      state = { status: 'ready', manifest };
    })
    .catch(() => {
      // データ 0 件と断定せず error として表示側へ伝える(manifest は前回値を保持)
      state = { ...state, status: 'error' };
    })
    .finally(() => {
      inflight = false;
      notify();
    });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!started) {
    started = true;
    load();
  }
  return () => listeners.delete(listener);
}

/** テスト専用: module store を初期状態へ戻す */
export function resetManifestStoreForTests() {
  state = { status: 'loading', manifest: EMPTY };
  inflight = false;
  started = false;
  listeners.clear();
}

/** Python site-data snapshot が生成した /manifest.json の共有 store を購読する */
export function useManifest(): ManifestState {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => state,
    () => state,
  );
  return { status: snapshot.status, manifest: snapshot.manifest, retry: load };
}
