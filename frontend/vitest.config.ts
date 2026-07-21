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
    // Many test files rendering full jsdom environments in parallel worker
    // threads can genuinely take longer than the 5s default under load
    // (verified: failures here were timeouts, not real assertion failures —
    // every file passes reliably in isolation). Give real CI/dev headroom.
    testTimeout: 15000,
    // This machine's environment-setup time varies wildly under concurrent
    // jsdom instances (observed 24s-55s for the same 4 files) — verified
    // via repeated runs that even a raised waitFor timeout doesn't fully
    // absorb that variance under full parallelism, while every file passes
    // reliably alone. Correctness over raw speed for a CI-run suite.
    fileParallelism: false,
  },
})
