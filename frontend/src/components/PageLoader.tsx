import { useEffect, useState } from 'react'
import chlorideExideBadge from '@/assets/chloride-exide-badge.webp'

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
      <div className="ce-loader">
        <div className="ce-loader__ring">
          <svg className="ce-loader__svg ce-loader__svg--outer" viewBox="0 0 120 120">
            <defs>
              <linearGradient id="ce-ringA" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="var(--ce-blue)" />
                <stop offset="1" stopColor="var(--ce-accent)" />
              </linearGradient>
            </defs>
            <circle cx="60" cy="60" r="54" fill="none" stroke="url(#ce-ringA)"
                    strokeWidth="5" strokeLinecap="round" strokeDasharray="96 243" />
          </svg>
          <svg className="ce-loader__svg ce-loader__svg--inner" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--ce-inner)"
                    strokeOpacity=".5" strokeWidth="3" strokeLinecap="round" strokeDasharray="40 250" />
          </svg>
          <img src={chlorideExideBadge} alt="Chloride Exide" className="ce-loader__badge" />
        </div>
      </div>
    </div>
  )
}

