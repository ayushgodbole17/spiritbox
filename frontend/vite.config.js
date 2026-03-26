import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    historyApiFallback: true,
    proxy: {
      '/ingest': 'http://api:8080',
      '/entries': 'http://api:8080',
      '/reminders': 'http://api:8080',
      '/health': 'http://api:8080',
      '/api/admin': 'http://api:8080',
      '/chat': 'http://api:8080',
    }
  }
})
