import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // 8001, not 8000 - another local project of mine already binds 127.0.0.1:8000,
        // which silently wins over this backend's 0.0.0.0:8000 for loopback traffic on Windows.
        target: 'http://localhost:8001',
        changeOrigin: true
      }
    }
  }
})