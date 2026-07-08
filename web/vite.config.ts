import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const referencesDir = path.join(repoRoot, 'tasks', 'references');
const runsDir = path.join(repoRoot, 'outputs', 'site-data');

/**
 * dev 時にリポジトリ側の tasks/references/*.png を /assets/references/ で配信する。
 * 本番はビルド後コピー(scripts/copy-references.mjs)、将来的には R2 配信に置き換わる。
 */
function serveTaskReferences(): Plugin {
  return {
    name: 'serve-task-references',
    configureServer(server) {
      server.middlewares.use('/assets/references', (req, res, next) => {
        const name = decodeURIComponent((req.url ?? '').split('?')[0].replace(/^\//, ''));
        if (!/^[a-z0-9-]+\.png$/.test(name)) return next();
        fs.readFile(path.join(referencesDir, name), (err, data) => {
          if (err) return next();
          res.setHeader('Content-Type', 'image/png');
          res.setHeader('Cache-Control', 'no-cache');
          res.end(data);
        });
      });
    },
  };
}

/** dev 時に outputs/site-data/ のベンチ成果物 GLB を /run-assets/ で配信する */
function serveRunOutputs(): Plugin {
  return {
    name: 'serve-run-outputs',
    configureServer(server) {
      server.middlewares.use('/run-assets', (req, res, next) => {
        const rel = decodeURIComponent((req.url ?? '').split('?')[0].replace(/^\//, ''));
        if (!/^[a-z0-9-]+\/[a-z0-9-]+\/output\.glb$/.test(rel)) return next();
        fs.readFile(path.join(runsDir, rel), (err, data) => {
          if (err) return next();
          res.setHeader('Content-Type', 'model/gltf-binary');
          res.setHeader('Cache-Control', 'no-cache');
          res.end(data);
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), serveTaskReferences(), serveRunOutputs()],
});
