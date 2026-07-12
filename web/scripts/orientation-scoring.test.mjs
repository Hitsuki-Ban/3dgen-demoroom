import assert from 'node:assert/strict';
import test from 'node:test';

import sharp from 'sharp';

import {
  AMBIGUITY_MARGIN,
  extractCandidateFeatures,
  extractReferenceMaskFeatures,
  rankOrientations,
  scoreOrientation,
} from './orientation-scoring.mjs';

const WIDTH = 48;
const HEIGHT = 40;

function asymmetricMask() {
  const mask = new Uint8Array(WIDTH * HEIGHT);
  for (let y = 6; y < 34; y += 1) {
    for (let x = 8; x < 17; x += 1) mask[y * WIDTH + x] = 1;
  }
  for (let y = 24; y < 34; y += 1) {
    for (let x = 8; x < 38; x += 1) mask[y * WIDTH + x] = 1;
  }
  for (let y = 12; y < 19; y += 1) {
    for (let x = 17; x < 27; x += 1) mask[y * WIDTH + x] = 1;
  }
  return mask;
}

function transformMask(source, transform) {
  const result = new Uint8Array(source.length);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      let sx;
      let sy;
      if (transform === 'mirror') {
        sx = WIDTH - 1 - x;
        sy = y;
      } else if (transform === 'rotate180') {
        sx = WIDTH - 1 - x;
        sy = HEIGHT - 1 - y;
      } else {
        sx = x;
        sy = y;
      }
      result[y * WIDTH + x] = source[sy * WIDTH + sx];
    }
  }
  return result;
}

async function referenceMaskPng(mask) {
  const data = Buffer.from(mask.map((value) => value * 255));
  return sharp(data, { raw: { width: WIDTH, height: HEIGHT, channels: 1 } }).toColourspace('b-w').png().toBuffer();
}

async function candidatePng(mask) {
  const data = Buffer.alloc(WIDTH * HEIGHT * 4);
  for (let index = 0; index < mask.length; index += 1) {
    data[index * 4] = 90;
    data[index * 4 + 1] = 140;
    data[index * 4 + 2] = 210;
    data[index * 4 + 3] = mask[index] ? 255 : 0;
  }
  return sharp(data, { raw: { width: WIDTH, height: HEIGHT, channels: 4 } }).png().toBuffer();
}

test('correct asymmetric orientation outranks mirrored and rotated candidates', async () => {
  const source = asymmetricMask();
  const reference = await extractReferenceMaskFeatures(await referenceMaskPng(source));
  const correct = await extractCandidateFeatures(await candidatePng(source));
  const mirrored = await extractCandidateFeatures(await candidatePng(transformMask(source, 'mirror')));
  const rotated = await extractCandidateFeatures(await candidatePng(transformMask(source, 'rotate180')));
  const ranking = rankOrientations(reference, [
    { id: 'mirror', features: mirrored },
    { id: 'correct', features: correct },
    { id: 'rotated', features: rotated },
  ]);

  assert.equal(ranking.top.id, 'correct');
  assert.ok(ranking.top.total > ranking.ranked.find(({ id }) => id === 'mirror').total);
  assert.ok(ranking.top.total > ranking.ranked.find(({ id }) => id === 'rotated').total);
  assert.ok(ranking.margin >= AMBIGUITY_MARGIN);
  assert.equal(ranking.ambiguous, false);
  for (const component of ['total', 'iou', 'edgeF1', 'spatial']) {
    assert.ok(ranking.top[component] >= 0 && ranking.top[component] <= 1);
  }
});

test('symmetric ties preserve input order and are marked ambiguous', async () => {
  const mask = new Uint8Array(WIDTH * HEIGHT);
  for (let y = 8; y < 32; y += 1) {
    for (let x = 12; x < 36; x += 1) mask[y * WIDTH + x] = 1;
  }
  const reference = await extractReferenceMaskFeatures(await referenceMaskPng(mask));
  const candidate = await extractCandidateFeatures(await candidatePng(mask));
  const ranking = rankOrientations(reference, [
    { id: 'first', features: candidate },
    { id: 'second', features: candidate },
  ]);

  assert.deepEqual(ranking.ranked.map(({ id }) => id), ['first', 'second']);
  assert.equal(ranking.margin, 0);
  assert.equal(ranking.ambiguous, true);
  assert.deepEqual(scoreOrientation(reference, candidate), { total: 1, iou: 1, edgeF1: 1, spatial: 1 });
});

test('invalid image inputs and pathological masks fail fast', async () => {
  await assert.rejects(extractReferenceMaskFeatures(Buffer.alloc(0)), /must not be empty/);
  await assert.rejects(extractCandidateFeatures(Buffer.alloc(0)), /must not be empty/);

  const transparent = new Uint8Array(WIDTH * HEIGHT);
  await assert.rejects(extractReferenceMaskFeatures(await referenceMaskPng(transparent)), /empty foreground/);
  await assert.rejects(extractCandidateFeatures(await candidatePng(transparent)), /empty foreground/);

  const opaque = new Uint8Array(WIDTH * HEIGHT).fill(1);
  await assert.rejects(extractReferenceMaskFeatures(await referenceMaskPng(opaque)), /foreground share/);
  await assert.rejects(extractCandidateFeatures(await candidatePng(opaque)), /foreground share/);

  const noAlpha = await sharp({
    create: { width: WIDTH, height: HEIGHT, channels: 3, background: '#334155' },
  }).png().toBuffer();
  await assert.rejects(extractCandidateFeatures(noAlpha), /must contain an alpha channel/);

  const nonBinary = Buffer.alloc(WIDTH * HEIGHT, 127);
  const nonBinaryPng = await sharp(nonBinary, { raw: { width: WIDTH, height: HEIGHT, channels: 1 } })
    .toColourspace('b-w')
    .png()
    .toBuffer();
  await assert.rejects(extractReferenceMaskFeatures(nonBinaryPng), /only 0 or 255/);

  const rgbMask = await sharp({
    create: { width: WIDTH, height: HEIGHT, channels: 3, background: '#ffffff' },
  }).png().toBuffer();
  await assert.rejects(extractReferenceMaskFeatures(rgbMask), /single-channel grayscale/);

  assert.throws(() => rankOrientations({}, []), /must be features/);
});
