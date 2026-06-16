import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { VitePWA } from 'vite-plugin-pwa';
import { resolve } from 'path';
import { mockApiPlugin } from '../shared/src/mock-auth-plugin';

export default defineConfig({
  plugins: [
    vue(),
    mockApiPlugin(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'icons/icon-192.png', 'icons/icon-512.png'],
      manifest: {
        name: '安卫智脑 · 巡检助手',
        short_name: '巡检助手',
        description: 'SafeGuard-AI 工业安全巡检工具',
        theme_color: '#FF6B35',
        background_color: '#0d1117',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^\/api\/v1\/knowledge/,
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'knowledge-cache', expiration: { maxEntries: 50, maxAgeSeconds: 86400 } },
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@safeguard/shared': resolve(__dirname, '../shared/src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
