import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer as createHttpServer } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';

import sharp from 'sharp';

import { createThumbnailRenderer, thumbnailRecipe } from './thumbnail-renderer.mjs';

async function occupyDefaultVitePort() {
  const server = createHttpServer((_request, response) => response.end('occupied'));
  const ownsPort = await new Promise((resolve, reject) => {
    server.once('error', (error) => {
      if (error.code === 'EADDRINUSE') resolve(false);
      else reject(error);
    });
    server.listen(5173, '127.0.0.1', () => resolve(true));
  });
  return ownsPort ? server : null;
}

function closeServer(server) {
  if (!server) return Promise.resolve();
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

function padChunk(bytes, fill = 0) {
  const padded = Buffer.alloc(Math.ceil(bytes.length / 4) * 4, fill);
  bytes.copy(padded);
  return padded;
}

function createTriangleGlb() {
  const binary = Buffer.alloc(80);
  const positions = [-0.5, -0.5, 0, 0.5, -0.5, 0, 0, 0.5, 0];
  const normals = [0, 0, 1, 0, 0, 1, 0, 0, 1];
  positions.forEach((value, index) => binary.writeFloatLE(value, index * 4));
  normals.forEach((value, index) => binary.writeFloatLE(value, 36 + index * 4));
  [0, 1, 2].forEach((value, index) => binary.writeUInt16LE(value, 72 + index * 2));

  const document = {
    asset: { version: '2.0', generator: '3dgen-thumbnail-smoke' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [
      {
        primitives: [
          {
            attributes: { POSITION: 0, NORMAL: 1 },
            indices: 2,
            material: 0,
          },
        ],
      },
    ],
    materials: [
      {
        pbrMetallicRoughness: {
          baseColorFactor: [0.15, 0.55, 0.95, 1],
          metallicFactor: 0,
          roughnessFactor: 0.55,
        },
        doubleSided: true,
      },
    ],
    buffers: [{ byteLength: binary.length }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: 36, target: 34962 },
      { buffer: 0, byteOffset: 36, byteLength: 36, target: 34962 },
      { buffer: 0, byteOffset: 72, byteLength: 6, target: 34963 },
    ],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: 3,
        type: 'VEC3',
        min: [-0.5, -0.5, 0],
        max: [0.5, 0.5, 0],
      },
      { bufferView: 1, componentType: 5126, count: 3, type: 'VEC3' },
      { bufferView: 2, componentType: 5123, count: 3, type: 'SCALAR' },
    ],
  };
  const json = padChunk(Buffer.from(JSON.stringify(document)), 0x20);
  const totalLength = 12 + 8 + json.length + 8 + binary.length;
  const glb = Buffer.alloc(totalLength);
  glb.writeUInt32LE(0x46546c67, 0);
  glb.writeUInt32LE(2, 4);
  glb.writeUInt32LE(totalLength, 8);
  glb.writeUInt32LE(json.length, 12);
  glb.writeUInt32LE(0x4e4f534a, 16);
  json.copy(glb, 20);
  const binaryHeader = 20 + json.length;
  glb.writeUInt32LE(binary.length, binaryHeader);
  glb.writeUInt32LE(0x004e4942, binaryHeader + 4);
  binary.copy(glb, binaryHeader + 8);
  return glb;
}

const root = await mkdtemp(path.join(tmpdir(), '3dgen-thumbnail-smoke-'));
const glbPath = path.join(root, 'triangle.glb');
const pngPath = path.join(root, 'triangle.png');
const webpPath = path.join(root, 'triangle.webp');
await writeFile(glbPath, createTriangleGlb());

const defaultPortBlocker = await occupyDefaultVitePort();
let renderer;
try {
  renderer = await createThumbnailRenderer({ backend: 'swiftshader', timeoutMs: 60_000 });
  const render = await renderer.render({
    glbPath,
    outputPath: pngPath,
    modelId: 'triposr',
    taskId: 'thumbnail-smoke',
  });
  assert.equal(render.width, 320);
  assert.equal(render.height, 320);
  assert.equal(render.stats.meshes, 1);
  assert.equal(render.stats.triangles, 1);
  assert.match(render.webglRenderer, /SwiftShader/i);

  await sharp(pngPath, { failOn: 'error' }).webp(thumbnailRecipe.webp).toFile(webpPath);
  const webp = await readFile(webpPath);
  const metadata = await sharp(webp, { failOn: 'error' }).metadata();
  assert.equal(metadata.format, 'webp');
  assert.equal(metadata.width, 320);
  assert.equal(metadata.height, 320);
  const { data, info } = await sharp(webp).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  let visiblePixels = 0;
  let brightestVisibleChannel = 0;
  for (let index = 3; index < data.length; index += info.channels) {
    if (data[index] !== 0) {
      visiblePixels += 1;
      brightestVisibleChannel = Math.max(
        brightestVisibleChannel,
        data[index - 3],
        data[index - 2],
        data[index - 1],
      );
    }
  }
  assert.ok(visiblePixels > 100, `expected visible model pixels, received ${visiblePixels}`);
  assert.ok(brightestVisibleChannel > 16, 'expected PBR/environment lighting to produce non-black pixels');
  process.stdout.write(
    `thumbnail render smoke: ${metadata.width}x${metadata.height} ${webp.length} bytes, ` +
      `${render.webglRenderer}\n`,
  );
} finally {
  await renderer?.close();
  await closeServer(defaultPortBlocker);
  await rm(root, { recursive: true, force: true });
}
