import '@testing-library/jest-dom/vitest'

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
