import { useEffect, useState } from 'react'

const LOADER_MIN_MS = 800
const startMs = performance.now()

interface PageLoaderProps {
  visible: boolean
}

export function PageLoader({ visible }: PageLoaderProps) {
  const [hiding, setHiding] = useState(false)
  const [removed, setRemoved] = useState(false)

  useEffect(() => {
    if (!visible) {
      const elapsed = performance.now() - startMs
      const remaining = Math.max(0, LOADER_MIN_MS - elapsed)
      const t1 = setTimeout(() => setHiding(true), remaining)
      const t2 = setTimeout(() => setRemoved(true), remaining + 550)
      return () => { clearTimeout(t1); clearTimeout(t2) }
    }
  }, [visible])

  if (removed) return null

  return (
    <div id="page-loader" className={hiding ? 'hide' : ''} aria-live="polite" aria-busy={!hiding}>
      {/* Battery SVG — same as static/index.html */}
      <svg
        className="loader-battery-svg"
        width="64" height="64"
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
      >
        <rect x="4" y="14" width="52" height="36" rx="4" stroke="#CC0000" strokeWidth="3"/>
        <rect x="20" y="8" width="8" height="6" rx="1" fill="#CC0000"/>
        <rect x="36" y="8" width="8" height="6" rx="1" fill="#CC0000"/>
        <path d="M28 26 L24 34 H30 L26 42 L38 28 H32 L36 20Z" fill="#CC0000"/>
      </svg>
      <div className="loader-bar-track">
        <div className="loader-bar-fill" />
      </div>
      <span className="loader-text">Loading Battery Finder...</span>
    </div>
  )
}

