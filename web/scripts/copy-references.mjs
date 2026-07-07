// ビルド成果物(dist)へリファレンス画像をコピーする。
// 将来 R2 配信に切り替えたらこのステップは不要になる。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const src = path.resolve(here, '../../tasks/references');
const dest = path.resolve(here, '../dist/assets/references');

fs.mkdirSync(dest, { recursive: true });
let count = 0;
for (const file of fs.readdirSync(src)) {
  if (!file.endsWith('.png')) continue;
  fs.copyFileSync(path.join(src, file), path.join(dest, file));
  count += 1;
}
console.log(`copied ${count} reference images -> ${dest}`);
