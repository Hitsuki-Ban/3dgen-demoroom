import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// vite.config.ts は dev 用ミドルウェア(manifest/参照画像の配信)を含むため、
// テストは副作用のない最小構成を別に持つ
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
