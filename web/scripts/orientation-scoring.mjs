import sharp from 'sharp';

export const NORMALIZED_SIZE = 64;
export const AMBIGUITY_MARGIN = 0.025;

const GRID_SIZE = 4;
const NORMALIZED_PADDING = 4;
const MIN_FOREGROUND_SHARE = 0.002;
const MAX_FOREGROUND_SHARE = 0.9;
const EDGE_TOLERANCE = 1;

function fail(message) {
  throw new Error(`orientation scoring: ${message}`);
}

function assertImageInput(input, label) {
  if (!(typeof input === 'string' || Buffer.isBuffer(input) || input instanceof Uint8Array)) {
    fail(`${label} input must be a path, Buffer, or Uint8Array`);
  }
  if ((Buffer.isBuffer(input) || input instanceof Uint8Array) && input.byteLength === 0) {
    fail(`${label} input must not be empty`);
  }
}

function validateSourceMask(mask, width, height, label) {
  let count = 0;
  for (const value of mask) count += value;
  const share = count / (width * height);
  if (count === 0) fail(`${label} segmentation produced an empty foreground mask`);
  if (share < MIN_FOREGROUND_SHARE || share > MAX_FOREGROUND_SHARE) {
    fail(`${label} foreground share ${share.toFixed(6)} is outside [${MIN_FOREGROUND_SHARE}, ${MAX_FOREGROUND_SHARE}]`);
  }
}

function foregroundBounds(mask, width, height) {
  let left = width;
  let top = height;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (mask[y * width + x] === 0) continue;
      left = Math.min(left, x);
      top = Math.min(top, y);
      right = Math.max(right, x);
      bottom = Math.max(bottom, y);
    }
  }
  if (right < left || bottom < top) fail('foreground bounding box is empty');
  return { left, top, width: right - left + 1, height: bottom - top + 1 };
}

function normalizeMask(source, width, height) {
  const bounds = foregroundBounds(source, width, height);
  const available = NORMALIZED_SIZE - 2 * NORMALIZED_PADDING;
  const scale = Math.min(available / bounds.width, available / bounds.height);
  const targetWidth = Math.max(1, Math.round(bounds.width * scale));
  const targetHeight = Math.max(1, Math.round(bounds.height * scale));
  const offsetX = Math.floor((NORMALIZED_SIZE - targetWidth) / 2);
  const offsetY = Math.floor((NORMALIZED_SIZE - targetHeight) / 2);
  const mask = new Uint8Array(NORMALIZED_SIZE * NORMALIZED_SIZE);

  for (let y = 0; y < targetHeight; y += 1) {
    const sourceY = bounds.top + Math.min(bounds.height - 1, Math.floor(((y + 0.5) * bounds.height) / targetHeight));
    for (let x = 0; x < targetWidth; x += 1) {
      const sourceX = bounds.left + Math.min(bounds.width - 1, Math.floor(((x + 0.5) * bounds.width) / targetWidth));
      mask[(offsetY + y) * NORMALIZED_SIZE + offsetX + x] = source[sourceY * width + sourceX];
    }
  }
  if (!mask.some(Boolean)) fail('normalized foreground mask is empty');
  return mask;
}

function edgeMask(mask) {
  const edges = new Uint8Array(mask.length);
  for (let y = 0; y < NORMALIZED_SIZE; y += 1) {
    for (let x = 0; x < NORMALIZED_SIZE; x += 1) {
      const index = y * NORMALIZED_SIZE + x;
      if (mask[index] === 0) continue;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          if (dx === 0 && dy === 0) continue;
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || nx >= NORMALIZED_SIZE || ny < 0 || ny >= NORMALIZED_SIZE || mask[ny * NORMALIZED_SIZE + nx] === 0) {
            edges[index] = 1;
          }
        }
      }
    }
  }
  return edges;
}

function occupancy(mask) {
  const result = new Float64Array(GRID_SIZE * GRID_SIZE);
  const cellSize = NORMALIZED_SIZE / GRID_SIZE;
  for (let gy = 0; gy < GRID_SIZE; gy += 1) {
    for (let gx = 0; gx < GRID_SIZE; gx += 1) {
      let count = 0;
      for (let y = gy * cellSize; y < (gy + 1) * cellSize; y += 1) {
        for (let x = gx * cellSize; x < (gx + 1) * cellSize; x += 1) count += mask[y * NORMALIZED_SIZE + x];
      }
      result[gy * GRID_SIZE + gx] = count / (cellSize * cellSize);
    }
  }
  return result;
}

function makeFeatures(sourceMask, width, height, label) {
  validateSourceMask(sourceMask, width, height, label);
  const mask = normalizeMask(sourceMask, width, height);
  return Object.freeze({
    size: NORMALIZED_SIZE,
    mask,
    edges: edgeMask(mask),
    occupancy: occupancy(mask),
  });
}

export async function extractReferenceMaskFeatures(input) {
  assertImageInput(input, 'reference mask');
  let metadata;
  let decoded;
  try {
    const image = sharp(input, { failOn: 'error' });
    metadata = await image.metadata();
    if (metadata.channels !== 1 || metadata.hasAlpha) {
      fail('reference mask must be a single-channel grayscale image without alpha');
    }
    decoded = await image.toColourspace('b-w').raw().toBuffer({ resolveWithObject: true });
  } catch (error) {
    if (error.message.startsWith('orientation scoring:')) throw error;
    fail(`reference mask decode failed: ${error.message}`);
  }
  const { data, info } = decoded;
  if (info.width < 2 || info.height < 2) fail('reference mask must be at least 2x2 pixels');
  const mask = new Uint8Array(info.width * info.height);
  for (let index = 0; index < mask.length; index += 1) {
    const value = data[index];
    if (value !== 0 && value !== 255) fail(`reference mask must contain only 0 or 255; found ${value}`);
    mask[index] = value === 255 ? 1 : 0;
  }
  return makeFeatures(mask, info.width, info.height, 'reference mask');
}

export async function extractCandidateFeatures(input) {
  assertImageInput(input, 'candidate');
  let metadata;
  let decoded;
  try {
    const image = sharp(input, { failOn: 'error' });
    metadata = await image.metadata();
    if (!metadata.hasAlpha) fail('candidate image must contain an alpha channel');
    decoded = await image.ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  } catch (error) {
    if (error.message.startsWith('orientation scoring:')) throw error;
    fail(`candidate image decode failed: ${error.message}`);
  }
  const { data, info } = decoded;
  if (info.width < 2 || info.height < 2) fail('candidate image must be at least 2x2 pixels');
  const mask = new Uint8Array(info.width * info.height);
  for (let index = 0; index < mask.length; index += 1) mask[index] = data[index * 4 + 3] >= 128 ? 1 : 0;
  return makeFeatures(mask, info.width, info.height, 'candidate');
}

function assertFeatures(features, label) {
  if (!features || features.size !== NORMALIZED_SIZE || !(features.mask instanceof Uint8Array)
    || features.mask.length !== NORMALIZED_SIZE ** 2 || !(features.edges instanceof Uint8Array)
    || features.edges.length !== NORMALIZED_SIZE ** 2 || !(features.occupancy instanceof Float64Array)
    || features.occupancy.length !== GRID_SIZE ** 2) {
    fail(`${label} must be features returned by an orientation feature extractor`);
  }
}

function maskIou(left, right) {
  let intersection = 0;
  let union = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] && right[index]) intersection += 1;
    if (left[index] || right[index]) union += 1;
  }
  if (union === 0) fail('cannot score empty normalized masks');
  return intersection / union;
}

function tolerantEdgeRecall(source, target) {
  let sourceCount = 0;
  let matched = 0;
  for (let y = 0; y < NORMALIZED_SIZE; y += 1) {
    for (let x = 0; x < NORMALIZED_SIZE; x += 1) {
      if (!source[y * NORMALIZED_SIZE + x]) continue;
      sourceCount += 1;
      let found = false;
      for (let dy = -EDGE_TOLERANCE; dy <= EDGE_TOLERANCE && !found; dy += 1) {
        for (let dx = -EDGE_TOLERANCE; dx <= EDGE_TOLERANCE; dx += 1) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && nx < NORMALIZED_SIZE && ny >= 0 && ny < NORMALIZED_SIZE && target[ny * NORMALIZED_SIZE + nx]) {
            found = true;
            break;
          }
        }
      }
      if (found) matched += 1;
    }
  }
  if (sourceCount === 0) fail('cannot score a mask without edges');
  return matched / sourceCount;
}

export function scoreOrientation(reference, candidate) {
  assertFeatures(reference, 'reference');
  assertFeatures(candidate, 'candidate');
  const iou = maskIou(reference.mask, candidate.mask);
  const precision = tolerantEdgeRecall(candidate.edges, reference.edges);
  const recall = tolerantEdgeRecall(reference.edges, candidate.edges);
  const edgeF1 = precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall);
  let occupancyDifference = 0;
  for (let index = 0; index < reference.occupancy.length; index += 1) {
    occupancyDifference += Math.abs(reference.occupancy[index] - candidate.occupancy[index]);
  }
  const spatial = 1 - occupancyDifference / reference.occupancy.length;
  const total = 0.55 * iou + 0.3 * edgeF1 + 0.15 * spatial;
  return Object.freeze({ total, iou, edgeF1, spatial });
}

export function rankOrientations(reference, candidates) {
  assertFeatures(reference, 'reference');
  if (!Array.isArray(candidates) || candidates.length === 0) fail('candidates must be a non-empty array');
  const ids = new Set();
  const ranked = candidates.map((candidate, index) => {
    if (!candidate || typeof candidate.id !== 'string' || candidate.id.length === 0) fail(`candidate ${index} must have a non-empty id`);
    if (ids.has(candidate.id)) fail(`candidate id ${JSON.stringify(candidate.id)} is duplicated`);
    ids.add(candidate.id);
    return Object.freeze({ id: candidate.id, index, ...scoreOrientation(reference, candidate.features) });
  }).sort((left, right) => right.total - left.total || left.index - right.index);
  const margin = ranked.length === 1 ? 1 : ranked[0].total - ranked[1].total;
  return Object.freeze({
    ranked: Object.freeze(ranked),
    top: ranked[0],
    margin,
    ambiguous: margin < AMBIGUITY_MARGIN,
  });
}
