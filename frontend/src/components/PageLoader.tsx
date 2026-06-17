import { useEffect, useState } from 'react'
import chlorideExideLogo from '@/assets/chlorideexidebrandlogo.webp'

const LOADER_MIN_MS = 2500
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
      <img
        src={chlorideExideLogo}
        alt="Chloride Exide"
        className="loader-battery-svg"
        style={{ width: 120, height: 'auto' }}
      />
      <div className="loader-bar-track">
        <div className="loader-bar-fill" />
      </div>

    </div>
  )
}

