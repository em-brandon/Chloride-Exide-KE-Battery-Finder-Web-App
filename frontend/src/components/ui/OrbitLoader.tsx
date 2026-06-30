import { useState } from 'react'
import chlorideExideBadge from '@/assets/chloride-exide-badge.webp'

interface OrbitLoaderProps {
  gradientId: string
  scale?: number
}

export function OrbitLoader({ gradientId, scale }: OrbitLoaderProps) {
  const [ringsVisible, setRingsVisible] = useState(false)

  const ringStyle: React.CSSProperties = {
    opacity: ringsVisible ? 1 : 0,
    transition: 'opacity 0.35s ease',
  }

  return (
    <div
      className="ce-loader"
      style={scale !== undefined ? { '--ce-scale': String(scale) } as React.CSSProperties : undefined}
    >
      <div className="ce-loader__ring">
        <svg className="ce-loader__svg ce-loader__svg--outer" viewBox="0 0 120 120" style={ringStyle}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="var(--ce-blue)" />
              <stop offset="1" stopColor="var(--ce-accent)" />
            </linearGradient>
          </defs>
          <circle cx="60" cy="60" r="54" fill="none" stroke={`url(#${gradientId})`}
                  strokeWidth="5" strokeLinecap="round" strokeDasharray="96 243" />
        </svg>
        <svg className="ce-loader__svg ce-loader__svg--inner" viewBox="0 0 120 120" style={ringStyle}>
          <circle cx="60" cy="60" r="52" fill="none" stroke="var(--ce-inner)"
                  strokeOpacity=".5" strokeWidth="3" strokeLinecap="round" strokeDasharray="40 250" />
        </svg>
        <img
          src={chlorideExideBadge}
          alt=""
          className="ce-loader__badge"
          onLoad={() => setRingsVisible(true)}
        />
      </div>
    </div>
  )
}
