import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard is compiled straight into the Python package so that
// `agentlens ui` can serve it from an installed wheel.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/agentlens/static',
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:4180',
    },
  },
})
