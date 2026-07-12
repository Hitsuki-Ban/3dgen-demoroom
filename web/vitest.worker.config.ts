import { cloudflareTest } from '@cloudflare/vitest-pool-workers';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: './wrangler.jsonc' },
      miniflare: {
        assets: {
          directory: './test/fixtures/assets',
          binding: 'ASSETS',
        },
      },
    }),
  ],
  test: {
    include: ['test/**/*.spec.ts'],
  },
});
