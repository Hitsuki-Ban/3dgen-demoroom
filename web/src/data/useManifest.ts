import { useEffect, useState } from 'react';
import type { SiteManifest } from './types';

const EMPTY: SiteManifest = { generatedAt: '', results: [] };
let cache: SiteManifest | null = null;

/** /manifest.json(build-manifest.mjs 生成)を一度だけ読み込む */
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
