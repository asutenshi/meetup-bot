import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Mini App раздаётся бэкендом под под-путём /app/ (см. src/meetup_bot/app.py,
// _mount_webapp). base обязан совпадать с точкой монтирования, иначе ссылки на
// ассеты в собранном index.html будут абсолютными от корня и не найдутся.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    // Стабильные имена без хеша не нужны — StaticFiles отдаёт с ETag, а
    // index.html не кешируется агрессивно (html=True в StaticFiles).
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    // В dev-режиме фронт ходит на бэкенд напрямую; чтобы не упираться в CORS,
    // проксируем API/health на локальный app (порт 8080 из docker-compose).
    proxy: {
      '/api': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
});
