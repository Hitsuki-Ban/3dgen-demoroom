// ビルド成果物(dist)へベンチ成果物 GLB をコピーする(将来 R2 配信に置き換え)。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '../../outputs/site-data');
const destRoot = path.resolve(here, '../dist/assets/runs');

let count = 0;
if (fs.existsSync(src)) {
  for (const modelId of fs.readdirSync(src)) {
    const modelDir = path.join(src, modelId);
    if (!fs.statSync(modelDir).isDirectory()) continue;
    for (const taskId of fs.readdirSync(modelDir)) {
      const glb = path.join(modelDir, taskId, 'output.glb');
      if (!fs.existsSync(glb)) continue;
      const dest = path.join(destRoot, modelId, taskId, 'output.glb');
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.copyFileSync(glb, dest);
      count += 1;
    }
  }
}
console.log(`copied ${count} run GLBs -> ${destRoot}`);
