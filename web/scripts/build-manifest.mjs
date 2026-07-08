// outputs/site-data/<model-id>/<task-id>/{output.glb, meta.json} を走査して
// サイト用 manifest (web/public/manifest.json) を生成する。
// GLB 自体は dev では vite ミドルウェア、build では copy-references.mjs 同様のコピーで配信する。
// 将来 R2 配信に切り替えたら glbUrl のベースだけ差し替える。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const runsRoot = path.resolve(here, '../../outputs/site-data');
const outFile = path.resolve(here, '../public/manifest.json');
const minResults = Number.parseInt(process.env.SITE_DATA_MIN_RESULTS ?? '', 10);

if (process.env.SITE_DATA_MIN_RESULTS && (!Number.isInteger(minResults) || minResults <= 0)) {
  throw new Error('SITE_DATA_MIN_RESULTS must be a positive integer');
}

const results = [];
if (fs.existsSync(runsRoot)) {
  for (const modelId of fs.readdirSync(runsRoot)) {
    const modelDir = path.join(runsRoot, modelId);
    if (!fs.statSync(modelDir).isDirectory()) continue;
    for (const taskId of fs.readdirSync(modelDir)) {
      const taskDir = path.join(modelDir, taskId);
      const metaPath = path.join(taskDir, 'meta.json');
      const glbPath = path.join(taskDir, 'output.glb');
      const hasMeta = fs.existsSync(metaPath);
      const hasGlb = fs.existsSync(glbPath);
      if (hasMeta !== hasGlb) {
        throw new Error(`incomplete site-data under ${taskDir}: meta.json=${hasMeta} output.glb=${hasGlb}`);
      }
      if (!hasMeta) continue;
      const meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
      if (meta.model_id !== modelId || meta.task_id !== taskId) {
        throw new Error(`meta.json mismatch under ${taskDir}: ${meta.model_id}/${meta.task_id}`);
      }
      results.push({
        taskId,
        modelId,
        glbUrl: `/run-assets/${modelId}/${taskId}/output.glb`,
        glbSizeBytes: fs.statSync(glbPath).size,
        meta,
      });
    }
  }
}

if (process.env.SITE_DATA_MIN_RESULTS && results.length < minResults) {
  throw new Error(`site-data result count ${results.length} is below required minimum ${minResults}`);
}

fs.mkdirSync(path.dirname(outFile), { recursive: true });
fs.writeFileSync(
  outFile,
  JSON.stringify({ generatedAt: new Date().toISOString(), results }, null, 2) + '\n',
  'utf-8',
);
console.log(`manifest: ${results.length} results -> ${outFile}`);
