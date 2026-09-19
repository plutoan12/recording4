import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['jassub'], include: ['jassub > throughput'] },
  server: {
    port: 5173,
    // 개발 중에는 /api 요청을 관리 API로 넘깁니다. 브라우저는 저장소 자격증명을 갖지 않습니다.
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
