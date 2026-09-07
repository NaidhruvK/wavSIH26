import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/analyze': 'http://127.0.0.1:8000',
      '/runs': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/registry': 'http://127.0.0.1:8000',
      '/envelope': 'http://127.0.0.1:8000',
    },
  },
  build: {
    chunkSizeWarningLimit: 4500,
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ['plotly.js-dist-min'],
        },
      },
    },
  },
});
