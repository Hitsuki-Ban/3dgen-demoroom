// 課題一覧カード用の軽量サムネイルを build 時に生成する(#51)。
// 原本 tasks/references/*.png(~1MiB/枚)は詳細ページ用に残し、
// 一覧は 320px WebP(数十 KB/枚)を使って初期転送を削減する。
// 出力先 web/public/assets/thumbs/ は gitignore(vite が dist へ自動コピー)。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.resolve(here, '../../tasks/references');
const destDir = path.resolve(here, '../public/assets/thumbs');

export const THUMB_SIZE = 320;

fs.mkdirSync(destDir, { recursive: true });

let generated = 0;
let skipped = 0;
let totalBytes = 0;

for (const file of fs.readdirSync(srcDir)) {
  if (!file.endsWith('.png')) continue;
  const src = path.join(srcDir, file);
  const dest = path.join(destDir, file.replace(/\.png$/, '.webp'));

  // インクリメンタル: 原本より新しい thumb があればスキップ
  if (fs.existsSync(dest) && fs.statSync(dest).mtimeMs >= fs.statSync(src).mtimeMs) {
    skipped += 1;
    totalBytes += fs.statSync(dest).size;
    continue;
  }

  await sharp(src).resize(THUMB_SIZE, THUMB_SIZE, { fit: 'cover' }).webp({ quality: 78 }).toFile(dest);
  generated += 1;
  totalBytes += fs.statSync(dest).size;
}

console.log(
  `thumbnails: ${generated} generated, ${skipped} up-to-date -> ${destDir} (total ${(totalBytes / 1024).toFixed(0)} KiB)`,
);
