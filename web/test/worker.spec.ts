import { env, exports } from 'cloudflare:workers';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import worker from '../src/worker';

const MODEL_ID = 'triposr';
const TASK_ID = 'task-one';
const OBJECT_KEY = `site-data/${MODEL_ID}/${TASK_ID}/output.glb`;
const ASSET_URL = `https://example.com/run-assets/${MODEL_ID}/${TASK_ID}/output.glb`;
const THUMB_OBJECT_KEY = `site-data/${MODEL_ID}/${TASK_ID}/thumb.webp`;
const THUMB_ASSET_URL = `https://example.com/run-assets/${MODEL_ID}/${TASK_ID}/thumb.webp?v=abc123`;
const RESTRICTED_OBJECT_KEY = 'site-data/hunyuan3d-21/task-one/output.glb';
const RESTRICTED_ASSET_URL = 'https://example.com/run-assets/hunyuan3d-21/task-one/output.glb';
const RESTRICTED_THUMB_OBJECT_KEY = 'site-data/hunyuan3d-21/task-one/thumb.webp';
const RESTRICTED_THUMB_ASSET_URL = 'https://example.com/run-assets/hunyuan3d-21/task-one/thumb.webp';
const BODY_TEXT = '0123456789';
const BODY = new TextEncoder().encode(BODY_TEXT);
const THUMB_BODY_TEXT = 'webp-thumbnail';
const THUMB_BODY = new TextEncoder().encode(THUMB_BODY_TEXT);

function assetRequest(headers?: HeadersInit, method = 'GET'): Request {
  return new Request(ASSET_URL, { method, headers });
}

async function fetchAsset(headers?: HeadersInit, method = 'GET'): Promise<Response> {
  return exports.default.fetch(assetRequest(headers, method));
}

function thumbRequest(headers?: HeadersInit, method = 'GET'): Request {
  return new Request(THUMB_ASSET_URL, { method, headers });
}

async function fetchThumb(headers?: HeadersInit, method = 'GET'): Promise<Response> {
  return exports.default.fetch(thumbRequest(headers, method));
}

function requestFromCountry(url: string, country: string, init?: RequestInit): Request {
  const request = new Request(url, init);
  Object.defineProperty(request, 'cf', { value: { country } });
  return request;
}

async function fetchFromCountry(url: string, country: string, init?: RequestInit): Promise<Response> {
  return worker.fetch(requestFromCountry(url, country, init), {
    ASSETS: env.ASSETS,
    SITE_DATA: env.SITE_DATA,
  });
}

async function responseBodyText(response: Response): Promise<string> {
  return new TextDecoder().decode(await response.arrayBuffer());
}

async function objectEtag(): Promise<string> {
  const object = await env.SITE_DATA.head(OBJECT_KEY);
  if (!object) throw new Error('test object is missing');
  return object.httpEtag;
}

function instrumentBucket(bucket: R2Bucket): {
  bucket: R2Bucket;
  calls: {
    headKeys: string[];
    getCalls: { key: string; options: R2GetOptions | undefined }[];
  };
} {
  const calls: {
    headKeys: string[];
    getCalls: { key: string; options: R2GetOptions | undefined }[];
  } = { headKeys: [], getCalls: [] };

  return {
    calls,
    bucket: new Proxy(bucket, {
      get(target, property, receiver) {
        if (property === 'head') {
          return (key: string) => {
            calls.headKeys.push(key);
            return target.head(key);
          };
        }
        if (property === 'get') {
          return (key: string, options?: R2GetOptions) => {
            calls.getCalls.push({ key, options });
            return target.get(key, options);
          };
        }
        const value = Reflect.get(target, property, receiver);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    }),
  };
}

function replacingBucket(key: string, replacements: Uint8Array[]): R2Bucket {
  let nextReplacement = 0;
  return new Proxy(env.SITE_DATA, {
    get(target, property, receiver) {
      if (property === 'get') {
        return async (requestedKey: string, options?: R2GetOptions) => {
          if (requestedKey === key && nextReplacement < replacements.length) {
            await target.put(key, replacements[nextReplacement]);
            nextReplacement += 1;
          }
          return target.get(requestedKey, options);
        };
      }
      const value = Reflect.get(target, property, receiver);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

beforeAll(async () => {
  await env.SITE_DATA.put(OBJECT_KEY, BODY, {
    httpMetadata: {
      contentType: 'application/octet-stream',
      contentLanguage: 'ja',
      contentDisposition: 'attachment; filename="output.glb"',
      cacheControl: 'max-age=60',
    },
  });
  await env.SITE_DATA.put(THUMB_OBJECT_KEY, THUMB_BODY, {
    httpMetadata: {
      contentType: 'application/octet-stream',
      cacheControl: 'public, max-age=31536000, immutable',
    },
  });
  await env.SITE_DATA.put(RESTRICTED_OBJECT_KEY, BODY);
  await env.SITE_DATA.put(RESTRICTED_THUMB_OBJECT_KEY, THUMB_BODY);
});

afterAll(async () => {
  await env.SITE_DATA.delete([
    OBJECT_KEY,
    THUMB_OBJECT_KEY,
    RESTRICTED_OBJECT_KEY,
    RESTRICTED_THUMB_OBJECT_KEY,
  ]);
});

describe('run asset full responses', () => {
  it('streams a full GET with immutable metadata and range capability', async () => {
    const response = await fetchAsset();

    expect(response.status).toBe(200);
    expect(await responseBodyText(response)).toBe(BODY_TEXT);
    expect(response.headers.get('Content-Type')).toBe('model/gltf-binary');
    expect(response.headers.get('Content-Length')).toBe(String(BODY.byteLength));
    expect(response.headers.get('Content-Language')).toBe('ja');
    expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="output.glb"');
    expect(response.headers.get('ETag')).toBe(await objectEtag());
    expect(response.headers.get('Cache-Control')).toBe('public, max-age=31536000, immutable');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
    expect(response.headers.has('Content-Range')).toBe(false);
  });

  it('keeps an unconditional full GET to one R2 get without a metadata read', async () => {
    const trace = instrumentBucket(env.SITE_DATA);
    const response = await worker.fetch(assetRequest(), { ASSETS: env.ASSETS, SITE_DATA: trace.bucket });

    expect(response.status).toBe(200);
    expect(await responseBodyText(response)).toBe(BODY_TEXT);
    expect(trace.calls.headKeys).toEqual([]);
    expect(trace.calls.getCalls).toEqual([{ key: OBJECT_KEY, options: undefined }]);
  });

  it('ignores Range on HEAD and preserves full-object metadata without a body', async () => {
    const response = await fetchAsset({ Range: 'bytes=0-3' }, 'HEAD');

    expect(response.status).toBe(200);
    expect((await response.arrayBuffer()).byteLength).toBe(0);
    expect(response.headers.get('Content-Length')).toBe(String(BODY.byteLength));
    expect(response.headers.get('Content-Type')).toBe('model/gltf-binary');
    expect(response.headers.get('Content-Language')).toBe('ja');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
    expect(response.headers.has('Content-Range')).toBe(false);
  });

  it('uses only R2 head for HEAD requests', async () => {
    const trace = instrumentBucket(env.SITE_DATA);
    const response = await worker.fetch(assetRequest(undefined, 'HEAD'), {
      ASSETS: env.ASSETS,
      SITE_DATA: trace.bucket,
    });

    expect(response.status).toBe(200);
    expect(trace.calls.headKeys).toEqual([OBJECT_KEY]);
    expect(trace.calls.getCalls).toEqual([]);
  });

  it('delegates non-run paths to the static assets binding', async () => {
    const response = await exports.default.fetch('https://example.com/');
    expect(response.status).toBe(200);
    expect((await responseBodyText(response)).trim()).toBe('static asset fallback');
  });
});

describe('thumbnail responses', () => {
  it('serves the exact thumb.webp asset with its image MIME and a revalidating cache policy', async () => {
    const response = await fetchThumb();

    expect(response.status).toBe(200);
    expect(await responseBodyText(response)).toBe(THUMB_BODY_TEXT);
    expect(response.headers.get('Content-Type')).toBe('image/webp');
    expect(response.headers.get('Content-Length')).toBe(String(THUMB_BODY.byteLength));
    expect(response.headers.get('Cache-Control')).toBe(
      'public, max-age=300, stale-while-revalidate=86400',
    );
    expect(response.headers.get('Cache-Control')).not.toContain('immutable');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
  });

  it('preserves the thumbnail cache policy on conditional 304 responses', async () => {
    const object = await env.SITE_DATA.head(THUMB_OBJECT_KEY);
    if (!object) throw new Error('test thumbnail is missing');

    const response = await fetchThumb({ 'If-None-Match': object.httpEtag });

    expect(response.status).toBe(304);
    expect(response.headers.get('ETag')).toBe(object.httpEtag);
    expect(response.headers.get('Cache-Control')).toBe(
      'public, max-age=300, stale-while-revalidate=86400',
    );
    expect(response.headers.has('Content-Type')).toBe(false);
  });

  it('serves a thumbnail HEAD without a body', async () => {
    const response = await fetchThumb(undefined, 'HEAD');

    expect(response.status).toBe(200);
    expect((await response.arrayBuffer()).byteLength).toBe(0);
    expect(response.headers.get('Content-Type')).toBe('image/webp');
    expect(response.headers.get('Content-Length')).toBe(String(THUMB_BODY.byteLength));
  });

  it('serves thumbnail byte ranges with the WebP MIME and thumbnail cache policy', async () => {
    const response = await fetchThumb({ Range: 'bytes=0-3' });

    expect(response.status).toBe(206);
    expect(await responseBodyText(response)).toBe(THUMB_BODY_TEXT.slice(0, 4));
    expect(response.headers.get('Content-Type')).toBe('image/webp');
    expect(response.headers.get('Content-Range')).toBe(`bytes 0-3/${THUMB_BODY.byteLength}`);
    expect(response.headers.get('Cache-Control')).toBe(
      'public, max-age=300, stale-while-revalidate=86400',
    );
  });
});

describe('single byte ranges', () => {
  it.each([
    ['bytes=0-3', '0123', 'bytes 0-3/10', '4'],
    ['bytes=4-', '456789', 'bytes 4-9/10', '6'],
    ['bytes=8-99', '89', 'bytes 8-9/10', '2'],
    ['bytes=-3', '789', 'bytes 7-9/10', '3'],
    ['bytes=-99', BODY_TEXT, 'bytes 0-9/10', '10'],
  ])('serves %s through the native R2 range path', async (range, body, contentRange, contentLength) => {
    const response = await fetchAsset({ Range: range });

    expect(response.status).toBe(206);
    expect(await responseBodyText(response)).toBe(body);
    expect(response.headers.get('Content-Range')).toBe(contentRange);
    expect(response.headers.get('Content-Length')).toBe(contentLength);
    expect(response.headers.get('Content-Type')).toBe('model/gltf-binary');
    expect(response.headers.get('Cache-Control')).toBe('public, max-age=31536000, immutable');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
  });

  it('passes the normalized range and metadata ETag to R2 get', async () => {
    const metadata = await env.SITE_DATA.head(OBJECT_KEY);
    if (!metadata) throw new Error('test object is missing');
    const trace = instrumentBucket(env.SITE_DATA);
    const response = await worker.fetch(assetRequest({ Range: 'bytes=2-5' }), {
      ASSETS: env.ASSETS,
      SITE_DATA: trace.bucket,
    });

    expect(response.status).toBe(206);
    expect(await responseBodyText(response)).toBe('2345');
    expect(trace.calls.headKeys).toEqual([OBJECT_KEY]);
    expect(trace.calls.getCalls).toEqual([
      {
        key: OBJECT_KEY,
        options: {
          onlyIf: { etagMatches: metadata.etag },
          range: { offset: 2, length: 4 },
        },
      },
    ]);
  });

  it.each(['bytes=10-', 'bytes=-0', 'bytes=999999999999999999999999-'])(
    'returns 416 with the selected representation size for %s',
    async (range) => {
      const response = await fetchAsset({ Range: range });

      expect(response.status).toBe(416);
      expect((await response.arrayBuffer()).byteLength).toBe(0);
      expect(response.headers.get('Content-Range')).toBe('bytes */10');
      expect(response.headers.get('Accept-Ranges')).toBe('bytes');
      expect(response.headers.get('Cache-Control')).toBe('no-store');
      expect(response.headers.has('Content-Length')).toBe(false);
    },
  );

  it.each(['bytes=5-3', 'bytes=abc', 'bytes=-'])('rejects malformed single ranges without Content-Range', async (range) => {
    const response = await fetchAsset({ Range: range });

    expect(response.status).toBe(400);
    expect(await responseBodyText(response)).toBe('Invalid Range');
    expect(response.headers.has('Content-Range')).toBe(false);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
  });

  it.each(['items=0-3', 'bytes=0-1,4-5'])('ignores unsupported or multipart range %s', async (range) => {
    const response = await fetchAsset({ Range: range });

    expect(response.status).toBe(200);
    expect(await responseBodyText(response)).toBe(BODY_TEXT);
    expect(response.headers.get('Content-Length')).toBe('10');
    expect(response.headers.has('Content-Range')).toBe(false);
  });
});

describe('conditional requests', () => {
  it.each([
    (etag: string) => etag,
    (etag: string) => `W/${etag}`,
    (etag: string) => `"old", W/${etag}`,
    () => '*',
  ])('returns 304 for a matching If-None-Match validator', async (validator) => {
    const response = await fetchAsset({ 'If-None-Match': validator(await objectEtag()) });

    expect(response.status).toBe(304);
    expect((await response.arrayBuffer()).byteLength).toBe(0);
    expect(response.headers.get('ETag')).toBe(await objectEtag());
    expect(response.headers.get('Cache-Control')).toBe('public, max-age=31536000, immutable');
    expect(response.headers.get('Accept-Ranges')).toBe('bytes');
    expect(response.headers.has('Content-Length')).toBe(false);
    expect(response.headers.has('Content-Range')).toBe(false);
    expect(response.headers.has('Content-Type')).toBe(false);
    expect(response.headers.has('Content-Language')).toBe(false);
    expect(response.headers.has('Content-Disposition')).toBe(false);
  });

  it('returns 304 for a conditional HEAD', async () => {
    const response = await fetchAsset({ 'If-None-Match': await objectEtag() }, 'HEAD');
    expect(response.status).toBe(304);
    expect((await response.arrayBuffer()).byteLength).toBe(0);
  });

  it('evaluates If-None-Match before Range', async () => {
    const response = await fetchAsset({
      'If-None-Match': await objectEtag(),
      Range: 'bytes=broken',
    });

    expect(response.status).toBe(304);
    expect(response.headers.has('Content-Range')).toBe(false);
  });

  it('serves a range when If-None-Match does not match', async () => {
    const response = await fetchAsset({
      'If-None-Match': '"old"',
      Range: 'bytes=0-3',
    });

    expect(response.status).toBe(206);
    expect(await responseBodyText(response)).toBe('0123');
  });

  it('honors only a matching strong ETag in If-Range', async () => {
    const response = await fetchAsset({
      'If-Range': await objectEtag(),
      Range: 'bytes=0-3',
    });

    expect(response.status).toBe(206);
    expect(await responseBodyText(response)).toBe('0123');
  });

  it.each(['"old"', 'W/', 'Sat, 29 Oct 1994 19:43:31 GMT'])(
    'falls back to a full 200 for a non-matching If-Range validator prefix %s',
    async (validatorPrefix) => {
      const validator = validatorPrefix === 'W/' ? `W/${await objectEtag()}` : validatorPrefix;
      const response = await fetchAsset({
        'If-Range': validator,
        Range: 'bytes=0-3',
      });

      expect(response.status).toBe(200);
      expect(await responseBodyText(response)).toBe(BODY_TEXT);
      expect(response.headers.get('Content-Length')).toBe('10');
      expect(response.headers.has('Content-Range')).toBe(false);
    },
  );

  it('ignores If-Range when Range is absent', async () => {
    const response = await fetchAsset({ 'If-Range': await objectEtag() });
    expect(response.status).toBe(200);
    expect(await responseBodyText(response)).toBe(BODY_TEXT);
  });
});

describe('immutable object version handoff', () => {
  it('re-evaluates the request once when the object changes after head', async () => {
    const key = 'site-data/triposr/race-once/output.glb';
    const url = 'https://example.com/run-assets/triposr/race-once/output.glb';
    await env.SITE_DATA.put(key, new TextEncoder().encode('0123456789'));

    try {
      const bucket = replacingBucket(key, [new TextEncoder().encode('abcdefghij')]);
      const response = await worker.fetch(new Request(url, { headers: { Range: 'bytes=0-3' } }), {
        ASSETS: env.ASSETS,
        SITE_DATA: bucket,
      });

      expect(response.status).toBe(206);
      expect(await responseBodyText(response)).toBe('abcd');
      expect(response.headers.get('Content-Range')).toBe('bytes 0-3/10');
    } finally {
      await env.SITE_DATA.delete(key);
    }
  });

  it('fails with an uncacheable 503 when the object changes twice', async () => {
    const key = 'site-data/triposr/race-repeat/output.glb';
    const url = 'https://example.com/run-assets/triposr/race-repeat/output.glb';
    await env.SITE_DATA.put(key, new TextEncoder().encode('0123456789'));

    try {
      const bucket = replacingBucket(key, [
        new TextEncoder().encode('abcdefghij'),
        new TextEncoder().encode('ABCDEFGHIJ'),
      ]);
      const response = await worker.fetch(new Request(url, { headers: { Range: 'bytes=0-3' } }), {
        ASSETS: env.ASSETS,
        SITE_DATA: bucket,
      });

      expect(response.status).toBe(503);
      expect(response.headers.get('Cache-Control')).toBe('no-store');
      expect(await responseBodyText(response)).toBe('Asset changed repeatedly while it was being read');
    } finally {
      await env.SITE_DATA.delete(key);
    }
  });
});

describe('routing and policy precedence', () => {
  it('prevents allowed Hunyuan responses from surviving a later geo decision', async () => {
    const metadata = await env.SITE_DATA.head(RESTRICTED_OBJECT_KEY);
    if (!metadata) throw new Error('restricted test object is missing');

    const responses = await Promise.all([
      fetchFromCountry(RESTRICTED_ASSET_URL, 'JP'),
      fetchFromCountry(RESTRICTED_ASSET_URL, 'JP', { method: 'HEAD' }),
      fetchFromCountry(RESTRICTED_ASSET_URL, 'JP', { headers: { Range: 'bytes=0-3' } }),
      fetchFromCountry(RESTRICTED_ASSET_URL, 'JP', {
        headers: { 'If-None-Match': metadata.httpEtag },
      }),
      fetchFromCountry(RESTRICTED_THUMB_ASSET_URL, 'JP'),
    ]);

    expect(responses.map((response) => response.status)).toEqual([200, 200, 206, 304, 200]);
    for (const response of responses) {
      expect(response.headers.get('Cache-Control')).toBe('no-store');
    }
  });

  it('returns 451 before object lookup, Range, or conditional evaluation', async () => {
    const forbiddenBucket = new Proxy(env.SITE_DATA, {
      get() {
        throw new Error('geo-blocked requests must not access R2');
      },
    });
    const response = await worker.fetch(
      new Request('https://example.com/run-assets/hunyuan3d-21/missing-task/output.glb', {
        headers: {
          'If-None-Match': '*',
          Range: 'bytes=0-3',
        },
      }),
      { ASSETS: env.ASSETS, SITE_DATA: forbiddenBucket },
    );

    expect(response.status).toBe(451);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(response.headers.has('Content-Range')).toBe(false);
  });

  it('returns an empty 451 response to HEAD', async () => {
    const response = await exports.default.fetch(
      new Request('https://example.com/run-assets/hunyuan3d-21/missing-task/output.glb', { method: 'HEAD' }),
    );
    expect(response.status).toBe(451);
    expect((await response.arrayBuffer()).byteLength).toBe(0);
  });

  it.each(['GET', 'HEAD'])('applies the Hunyuan geo restriction to thumbnail %s before object lookup', async (method) => {
    const forbiddenBucket = new Proxy(env.SITE_DATA, {
      get() {
        throw new Error('geo-blocked thumbnail requests must not access R2');
      },
    });
    const response = await worker.fetch(
      new Request('https://example.com/run-assets/hunyuan3d-21/missing-task/thumb.webp', { method }),
      { ASSETS: env.ASSETS, SITE_DATA: forbiddenBucket },
    );

    expect(response.status).toBe(451);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    if (method === 'HEAD') expect((await response.arrayBuffer()).byteLength).toBe(0);
  });

  it.each([
    'preview.webp',
    'thumb.png',
    'nested/thumb.webp',
    'thumb.webp.bak',
  ])('keeps non-contract run asset %s outside the R2 whitelist', async (name) => {
    const response = await exports.default.fetch(
      `https://example.com/run-assets/${MODEL_ID}/${TASK_ID}/${name}`,
    );
    expect(response.status).toBe(404);
  });

  it('returns 404 for a missing unrestricted object even with If-None-Match star', async () => {
    const response = await exports.default.fetch(
      new Request('https://example.com/run-assets/triposr/missing-task/output.glb', {
        headers: { 'If-None-Match': '*' },
      }),
    );
    expect(response.status).toBe(404);
  });

  it('rejects unsupported methods before object access', async () => {
    const response = await fetchAsset(undefined, 'POST');
    expect(response.status).toBe(405);
    expect(response.headers.get('Allow')).toBe('GET, HEAD');
  });
});
