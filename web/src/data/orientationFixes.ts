/** セル(model×task)単位の viewing orientation registry(#85)。
 *  生成 GLB は無修正のまま、表示時にだけ absolute 回転(度、XYZ order)を適用して
 *  同一課題のモデル間で向きを揃える。生成・検証は web/scripts/orientation-*.mjs、
 *  根拠は orientation-selected-evidence.json と docs/research/orientation-alignment-codex.md。 */
import { MODELS } from './models';
import registry from './orientation-fixes.json';

export interface OrientationDegrees {
  x: number;
  y: number;
  z: number;
}

interface CellRecord {
  status: string;
  rotationDegrees?: OrientationDegrees;
}

const CELLS: Record<string, CellRecord> = registry.cells;

// registry と表示側の前提がずれたら起動時に気付けるようにする
// (ViewerCore は THREE.Euler 既定の XYZ・object-local で適用する)
if (registry.schemaVersion !== 1 || registry.eulerOrder !== 'XYZ' || registry.rotationSpace !== 'absolute-object-local') {
  throw new Error('orientation-fixes.json schema mismatch: viewer expects schemaVersion 1 / XYZ / absolute-object-local');
}

/** セルの viewing 回転を解決する。
 *  cell record(absolute)が model 既定 fix を**置き換える**(加算しない)。
 *  cell が無い/excluded の場合のみ model 既定へフォールバック(将来の未整列セル用)。 */
export function resolveOrientationFix(modelId: string, taskId: string): OrientationDegrees | undefined {
  const cell = CELLS[`${modelId}/${taskId}`];
  if (cell?.status === 'fixed' && cell.rotationDegrees) return cell.rotationDegrees;
  const model = MODELS.find((m) => m.id === modelId);
  const fix = model?.orientationFix;
  return fix ? { x: fix.x ?? 0, y: fix.y ?? 0, z: fix.z ?? 0 } : undefined;
}
