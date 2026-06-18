import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',          // LAN/WAN 바인딩
    port: 5173,
    // WAN 접속 허용 (라우터 포워딩 210.220.187.209:10080 → 5173). Vite 호스트 차단 회피.
    allowedHosts: ['210.220.187.209', 'localhost', '127.0.0.1'],
    // HMR 은 페이지 포트(WAN=10080)로 ws 연결 — 라우터가 10080→5173 포워딩하므로 외부에서도 동작
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
