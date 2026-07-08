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
