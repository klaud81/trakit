import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // /api 요청을 백엔드 FastAPI 서버로 포워드
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        ws: true, // /api/ws/* WebSocket 프록시 (VI 차익거래 실시간)
      },
    },
  },
});
