import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const referencesDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../tasks/references',
);

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

export default defineConfig({
  plugins: [react(), tailwindcss(), serveTaskReferences()],
});
