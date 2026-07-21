import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

// waitFor()'s default internal timeout (1000ms) is separate from Vitest's
// own testTimeout. Components using useTransition (e.g. AdminAuditLog) can
// occasionally take just over 1000ms to flush under jsdom's scheduling,
// especially with several test files' work still settling in the same
// process — an intermittent, narrow-margin timing issue, not a real hang.
// Raise the default so waitFor has realistic headroom across the suite.
configure({ asyncUtilTimeout: 5000 })

// jsdom doesn't implement matchMedia — useIsMobile() (lib/utils.ts) and
// anything that renders it call this on every mount.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList
}
