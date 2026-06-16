import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import UnoCSS from 'unocss/vite';
import { resolve } from 'path';
import { mockApiPlugin } from '../shared/src/mock-auth-plugin';

export default defineConfig({
  plugins: [vue(), UnoCSS(), mockApiPlugin()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@safeguard/shared': resolve(__dirname, '../shared/src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
