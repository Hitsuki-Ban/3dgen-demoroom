interface AssetsBinding {
  fetch(request: Request): Promise<Response>;
}

interface R2ObjectMetadata {
  size: number;
  httpEtag: string;
  uploaded: Date;
  writeHttpMetadata(headers: Headers): void;
}

interface R2ObjectBody extends R2ObjectMetadata {
  body: ReadableStream<Uint8Array>;
}

interface R2BucketBinding {
  get(key: string): Promise<R2ObjectBody | null>;
  head(key: string): Promise<R2ObjectMetadata | null>;
}

interface Env {
  ASSETS: AssetsBinding;
  SITE_DATA: R2BucketBinding;
}

const RUN_ASSET_PREFIX = '/run-assets/';
const RUN_OUTPUT_RE = /^[a-z0-9-]+\/[a-z0-9-]+\/output\.glb$/;

// Tencent Hunyuan3D 2.1 Community License 5(c): Territory(EU/UK/韓国を除く全世界)外への
// Output の表示・配信が禁止されるため、当該地域からの取得をエッジで遮断する。
// docs/research/models-merged.md「Hunyuan3D 2.1 の扱い」参照。
const GEO_RESTRICTED_MODELS = new Set(['hunyuan3d-21']);
// EU27 + GB + KR(ISO 3166-1 alpha-2)
const GEO_BLOCKED_COUNTRIES = new Set([
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU',
  'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
  'GB', 'KR',
]);

/** ブロック対象モデルのアセットか、および閲覧国コードから遮断要否を判定する。
 * 国が判定できない場合はライセンス安全側(遮断)に倒す。 */
export function isGeoBlocked(key: string, country: string | undefined): boolean {
  const modelId = key.slice('site-data/'.length).split('/')[0];
  if (!GEO_RESTRICTED_MODELS.has(modelId)) return false;
  return !country || GEO_BLOCKED_COUNTRIES.has(country);
}

function runAssetKey(pathname: string): string | null {
  if (!pathname.startsWith(RUN_ASSET_PREFIX)) return null;
  const relativePath = decodeURIComponent(pathname.slice(RUN_ASSET_PREFIX.length));
  if (!RUN_OUTPUT_RE.test(relativePath)) return null;
  return `site-data/${relativePath}`;
}

function runAssetHeaders(object: R2ObjectMetadata): Headers {
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('Content-Type', 'model/gltf-binary');
  headers.set('Content-Length', String(object.size));
  headers.set('ETag', object.httpEtag);
  headers.set('Cache-Control', 'public, max-age=31536000, immutable');
  return headers;
}

async function serveRunAsset(request: Request, env: Env, key: string): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', {
      status: 405,
      headers: { Allow: 'GET, HEAD' },
    });
  }

  const country = (request as Request & { cf?: { country?: string } }).cf?.country;
  if (isGeoBlocked(key, country)) {
    return new Response(
      'Unavailable For Legal Reasons: Tencent Hunyuan3D 2.1 Community License 5(c) restricts use and display of outputs outside its Territory (worldwide except EU/UK/South Korea).',
      {
        status: 451,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          // 国判定に依存するレスポンスなので共有キャッシュに載せない
          'Cache-Control': 'no-store',
        },
      },
    );
  }

  if (request.method === 'HEAD') {
    const object = await env.SITE_DATA.head(key);
    if (!object) return new Response('Not Found', { status: 404 });
    return new Response(null, { headers: runAssetHeaders(object) });
  }

  const object = await env.SITE_DATA.get(key);
  if (!object) return new Response('Not Found', { status: 404 });
  return new Response(object.body, { headers: runAssetHeaders(object) });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const key = runAssetKey(url.pathname);
    if (key) return serveRunAsset(request, env, key);
    if (url.pathname.startsWith(RUN_ASSET_PREFIX)) return new Response('Not Found', { status: 404 });
    return env.ASSETS.fetch(request);
  },
};
