import { useEffect, useState } from 'react';
import type { SiteManifest } from './types';

const EMPTY: SiteManifest = { generatedAt: '', partial: false, entries: [] };
let cache: SiteManifest | null = null;

/** Python site-data snapshot が生成した /manifest.json を一度だけ読み込む */
export function useManifest(): SiteManifest {
  const [manifest, setManifest] = useState<SiteManifest>(cache ?? EMPTY);

  useEffect(() => {
    if (cache) return;
    let cancelled = false;
    fetch('/manifest.json')
      .then((r) => (r.ok ? (r.json() as Promise<SiteManifest>) : EMPTY))
      .then((m) => {
        cache = m;
        if (!cancelled) setManifest(m);
      })
      .catch(() => {
        cache = EMPTY;
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return manifest;
}
