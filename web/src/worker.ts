const RUN_ASSET_PREFIX = '/run-assets/';
const RUN_OUTPUT_RE = /^[a-z0-9-]+\/[a-z0-9-]+\/(?:output\.glb|thumb\.webp)$/;
const RANGE_UNIT_RE = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const GLB_CACHE_CONTROL = 'public, max-age=31536000, immutable';
const THUMB_CACHE_CONTROL = 'public, max-age=300, stale-while-revalidate=86400';

type NormalizedRange = {
  start: number;
  end: number;
};

type RangeDecision =
  | { kind: 'range'; range: NormalizedRange }
  | { kind: 'ignore' }
  | { kind: 'invalid' }
  | { kind: 'unsatisfiable' };

// Tencent Hunyuan3D 2.1 Community License 5(c): Territory(EU/UK/韓国を除く全世界)外への
// Output の表示・配信が禁止されるため、当該地域からの取得をエッジで遮断する。
// docs/research/models-merged.md「Hunyuan3D 2.1 の扱い」参照。
const GEO_RESTRICTED_MODELS = new Set(['hunyuan3d-21']);
// Cloudflare が ip.src.is_in_european_union=true とする 34 コード + GB + KR。
// EU 加盟国 27 コードに加え、EU 領域として別 ISO code を持つ AX/GF/GP/MF/MQ/RE/YT を含む。
const GEO_BLOCKED_COUNTRIES = new Set([
  'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF',
  'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL',
  'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT',
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

function runAssetContentType(key: string): string {
  if (key.endsWith('/output.glb')) return 'model/gltf-binary';
  if (key.endsWith('/thumb.webp')) return 'image/webp';
  throw new Error(`unsupported run asset key: ${key}`);
}

function runAssetCacheControl(key: string): string {
  return key.endsWith('/thumb.webp') ? THUMB_CACHE_CONTROL : GLB_CACHE_CONTROL;
}

function runAssetHeaders(key: string, object: R2Object, contentLength: number | null): Headers {
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('Content-Type', runAssetContentType(key));
  if (contentLength === null) headers.delete('Content-Length');
  else headers.set('Content-Length', String(contentLength));
  headers.set('ETag', object.httpEtag);
  headers.set('Cache-Control', runAssetCacheControl(key));
  headers.set('Accept-Ranges', 'bytes');
  return headers;
}

function rangeFailureHeaders(object: R2Object, contentRange?: string): Headers {
  const headers = new Headers({
    'Accept-Ranges': 'bytes',
    'Cache-Control': 'no-store',
    ETag: object.httpEtag,
  });
  if (contentRange) headers.set('Content-Range', contentRange);
  return headers;
}

function notModified(key: string, object: R2Object): Response {
  const headers = new Headers({
    'Accept-Ranges': 'bytes',
    'Cache-Control': runAssetCacheControl(key),
    ETag: object.httpEtag,
  });
  return new Response(null, {
    status: 304,
    headers,
  });
}

function versionChangedResponse(): Response {
  return new Response('Asset changed repeatedly while it was being read', {
    status: 503,
    headers: {
      'Cache-Control': 'no-store',
      'Content-Type': 'text/plain; charset=utf-8',
    },
  });
}

function isEntityTagCharacter(code: number): boolean {
  return code === 0x21 || (code >= 0x23 && code <= 0x7e) || code >= 0x80;
}

/** RFC 9110 の If-None-Match 弱比較。無効な field-value は条件なしとして扱う。 */
function ifNoneMatchMatches(value: string, currentHttpEtag: string): boolean {
  const trimmed = value.trim();
  if (trimmed === '*') return true;

  const currentOpaqueTag = currentHttpEtag.startsWith('W/') ? currentHttpEtag.slice(2) : currentHttpEtag;
  let matched = false;
  let offset = 0;

  while (offset < value.length) {
    while (value[offset] === ' ' || value[offset] === '\t') offset += 1;
    if (value.startsWith('W/', offset)) offset += 2;
    if (value[offset] !== '"') return false;

    const tagStart = offset;
    offset += 1;
    while (offset < value.length && value[offset] !== '"') {
      if (!isEntityTagCharacter(value.charCodeAt(offset))) return false;
      offset += 1;
    }
    if (offset >= value.length) return false;
    offset += 1;

    if (value.slice(tagStart, offset) === currentOpaqueTag) matched = true;
    while (value[offset] === ' ' || value[offset] === '\t') offset += 1;
    if (offset === value.length) return matched;
    if (value[offset] !== ',') return false;
    offset += 1;
    if (offset === value.length) return false;
  }

  return false;
}

function parseDecimal(value: string): bigint | null {
  if (!/^\d+$/.test(value)) return null;
  try {
    return BigInt(value);
  } catch {
    return null;
  }
}

/** RFC 9110 の単一 bytes range を R2 が受け取れる閉区間へ正規化する。 */
function parseRangeHeader(value: string, size: number): RangeDecision {
  const separator = value.indexOf('=');
  if (separator <= 0) return { kind: 'invalid' };

  const unit = value.slice(0, separator);
  if (!RANGE_UNIT_RE.test(unit)) return { kind: 'invalid' };
  if (unit.toLowerCase() !== 'bytes') return { kind: 'ignore' };

  const rangeSet = value.slice(separator + 1).trim();
  // Multipart 206 は本 Worker の対象外。合法な複数 range は通常 GET として処理する。
  if (rangeSet.includes(',')) return { kind: 'ignore' };

  const match = /^(\d*)-(\d*)$/.exec(rangeSet);
  if (!match || (!match[1] && !match[2])) return { kind: 'invalid' };

  const sizeBigInt = BigInt(size);
  if (!match[1]) {
    const suffixLength = parseDecimal(match[2]);
    if (suffixLength === null) return { kind: 'invalid' };
    if (suffixLength === 0n || size === 0) return { kind: 'unsatisfiable' };

    const actualLength = suffixLength >= sizeBigInt ? size : Number(suffixLength);
    return {
      kind: 'range',
      range: { start: size - actualLength, end: size - 1 },
    };
  }

  const first = parseDecimal(match[1]);
  const last = match[2] ? parseDecimal(match[2]) : null;
  if (first === null || (match[2] && last === null)) return { kind: 'invalid' };
  if (last !== null && last < first) return { kind: 'invalid' };
  if (first >= sizeBigInt) return { kind: 'unsatisfiable' };

  const end = last === null || last >= sizeBigInt ? size - 1 : Number(last);
  return {
    kind: 'range',
    range: { start: Number(first), end },
  };
}

function ifRangeMatches(value: string, object: R2Object): boolean {
  // R2 uploaded は強い Last-Modified validator と保証されないため、強 ETag だけを受理する。
  return !value.startsWith('W/') && value === object.httpEtag;
}

async function repeatAfterVersionChange(
  request: Request,
  env: Env,
  key: string,
  canRepeat: boolean,
): Promise<Response> {
  if (!canRepeat) return versionChangedResponse();
  return serveRunAsset(request, env, key, false);
}

async function getMatchingObject(
  request: Request,
  env: Env,
  key: string,
  metadata: R2Object,
  canRepeat: boolean,
): Promise<Response> {
  const object = await env.SITE_DATA.get(key, {
    onlyIf: { etagMatches: metadata.etag },
  });
  if (!object) return new Response('Not Found', { status: 404 });
  if (!('body' in object)) return repeatAfterVersionChange(request, env, key, canRepeat);
  return new Response(object.body, { headers: runAssetHeaders(key, object, object.size) });
}

async function getMatchingRange(
  request: Request,
  env: Env,
  key: string,
  metadata: R2Object,
  range: NormalizedRange,
  canRepeat: boolean,
): Promise<Response> {
  const contentLength = range.end - range.start + 1;
  const object = await env.SITE_DATA.get(key, {
    range: { offset: range.start, length: contentLength },
    onlyIf: { etagMatches: metadata.etag },
  });
  if (!object) return new Response('Not Found', { status: 404 });
  if (!('body' in object)) return repeatAfterVersionChange(request, env, key, canRepeat);

  const headers = runAssetHeaders(key, object, contentLength);
  headers.set('Content-Range', `bytes ${range.start}-${range.end}/${object.size}`);
  return new Response(object.body, { status: 206, headers });
}

async function serveRunAsset(request: Request, env: Env, key: string, canRepeat = true): Promise<Response> {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', {
      status: 405,
      headers: { Allow: 'GET, HEAD' },
    });
  }

  const country = request.cf?.country;
  if (isGeoBlocked(key, typeof country === 'string' ? country : undefined)) {
    return new Response(
      request.method === 'HEAD'
        ? null
        : 'Unavailable For Legal Reasons: Tencent Hunyuan3D 2.1 Community License 5(c) restricts use and display of outputs outside its Territory (worldwide except EU/UK/South Korea).',
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

  const rangeHeader = request.method === 'GET' ? request.headers.get('Range') : null;
  const ifNoneMatch = request.headers.get('If-None-Match');

  if (request.method === 'HEAD' || rangeHeader !== null || ifNoneMatch !== null) {
    const metadata = await env.SITE_DATA.head(key);
    if (!metadata) return new Response('Not Found', { status: 404 });

    if (ifNoneMatch !== null && ifNoneMatchMatches(ifNoneMatch, metadata.httpEtag)) {
      return notModified(key, metadata);
    }

    if (request.method === 'HEAD') {
      return new Response(null, { headers: runAssetHeaders(key, metadata, metadata.size) });
    }

    if (rangeHeader === null) return getMatchingObject(request, env, key, metadata, canRepeat);

    const ifRange = request.headers.get('If-Range');
    if (ifRange !== null && !ifRangeMatches(ifRange, metadata)) {
      return getMatchingObject(request, env, key, metadata, canRepeat);
    }

    const rangeDecision = parseRangeHeader(rangeHeader, metadata.size);
    if (rangeDecision.kind === 'ignore') return getMatchingObject(request, env, key, metadata, canRepeat);
    if (rangeDecision.kind === 'invalid') {
      const headers = rangeFailureHeaders(metadata);
      headers.set('Content-Type', 'text/plain; charset=utf-8');
      return new Response('Invalid Range', { status: 400, headers });
    }
    if (rangeDecision.kind === 'unsatisfiable') {
      return new Response(null, {
        status: 416,
        headers: rangeFailureHeaders(metadata, `bytes */${metadata.size}`),
      });
    }
    return getMatchingRange(request, env, key, metadata, rangeDecision.range, canRepeat);
  }

  // #52 の進捗表示が使う通常 GET は、追加 HEAD なしの単一 R2 read を維持する。
  const object = await env.SITE_DATA.get(key);
  if (!object) return new Response('Not Found', { status: 404 });
  return new Response(object.body, { headers: runAssetHeaders(key, object, object.size) });
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
