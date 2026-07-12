// 課題一覧カード用の軽量サムネイルを build 時に生成する(#51)。
// 原本 tasks/references/*.png(~1MiB/枚)は詳細ページ用に残し、
// 一覧は 320px WebP(数十 KB/枚)を使って初期転送を削減する。
// 出力先 web/public/assets/thumbs/ は gitignore(vite が dist へ自動コピー)。
//
// 鮮度判定は mtime ではなく「原本の content hash + 生成レシピ」で行う
// (PR #77 レビュー指摘: CI キャッシュ復元で mtime が逆転しても、
//  レシピ変更で原本が変わらなくても、正しく再生成される)。
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import sharp from 'sharp';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcDir = path.resolve(here, '../../tasks/references');
const destDir = path.resolve(here, '../public/assets/thumbs');
const buildManifestPath = path.join(destDir, '.build-manifest.json');

/** 生成レシピ。ここを変えると全サムネイルが再生成される */
const RECIPE = {
  size: 320,
  fit: 'cover',
  format: 'webp',
  quality: 78,
  sharp: sharp.versions.sharp,
};

fs.mkdirSync(destDir, { recursive: true });

/** @type {{ recipe?: object, files?: Record<string, string> }} */
let previous = {};
try {
  previous = JSON.parse(fs.readFileSync(buildManifestPath, 'utf8'));
} catch {
  // 初回 or 破損時は全生成
}
const recipeChanged = JSON.stringify(previous.recipe) !== JSON.stringify(RECIPE);

const sources = fs.readdirSync(srcDir).filter((f) => f.endsWith('.png'));
const files = {};
let generated = 0;
let skipped = 0;
let totalBytes = 0;

for (const file of sources) {
  const src = path.join(srcDir, file);
  const dest = path.join(destDir, file.replace(/\.png$/, '.webp'));
  const hash = crypto.createHash('sha256').update(fs.readFileSync(src)).digest('hex').slice(0, 16);
  files[file] = hash;

  if (!recipeChanged && previous.files?.[file] === hash && fs.existsSync(dest)) {
    skipped += 1;
    totalBytes += fs.statSync(dest).size;
    continue;
  }

  await sharp(src)
    .resize(RECIPE.size, RECIPE.size, { fit: RECIPE.fit })
    .webp({ quality: RECIPE.quality })
    .toFile(dest);
  generated += 1;
  totalBytes += fs.statSync(dest).size;
}

// 原本が消えた課題の thumb を掃除する(改名・削除時に古い画像を配信しない)
const expected = new Set(sources.map((f) => f.replace(/\.png$/, '.webp')));
let removed = 0;
for (const f of fs.readdirSync(destDir)) {
  if (f.endsWith('.webp') && !expected.has(f)) {
    fs.unlinkSync(path.join(destDir, f));
    removed += 1;
  }
}

fs.writeFileSync(buildManifestPath, JSON.stringify({ recipe: RECIPE, files }, null, 2));

console.log(
  `thumbnails: ${generated} generated, ${skipped} up-to-date, ${removed} removed -> ${destDir} (total ${(totalBytes / 1024).toFixed(0)} KiB)`,
);
