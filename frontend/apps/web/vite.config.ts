import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 선주·해경 웹. EC2 백엔드에 붙는다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 개발 중에는 프록시로 CORS를 아예 발생시키지 않는다.
    // 브라우저가 localhost:5173 하고만 대화하게 된다.
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8080', ws: true },
    },
  },
});
