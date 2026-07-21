import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// React/react-dom's dev-vs-production build selection is driven by
// process.env.NODE_ENV. If the shell (or a CI agent) already has it set to
// "production" — a real thing that happens, since bun run build wants it —
// react-dom resolves its production bundle inside jsdom, and its
// react-dom/test-utils act() shim breaks against that combination. Test
// runs must never inherit an ambient "production" NODE_ENV.
process.env.NODE_ENV = 'test'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
  },
})
