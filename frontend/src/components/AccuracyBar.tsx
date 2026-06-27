import { useEffect, useState } from 'react'
import type { RecommendationResult } from '@/types/battery'

type Factors = { model: number; year: number; source: number; specs: number }

function calcFactors(data: RecommendationResult): Factors {
  const mt = (data.match_type ?? '').toLowerCase()
  const isRealWorld = mt.includes('real')
  const isExact     = mt.includes('exact')
  const isClose     = mt.includes('close')
  const hasModel    = !!data.matched_make

  // Car found: 0–50 pts
  let model: number
  if (isRealWorld || isExact) model = 50
  else if (isClose) model = Math.round(20 + ((Math.min(data.confidence, 89) - 60) / 29) * 20)
  else model = 0

  // Year match: 0–25 pts
  let year = 0
  if (data.matched_year != null) {
    const delta = Math.abs(data.matched_year - data.year)
    year = delta === 0 ? 25 : delta === 1 ? 20 : delta === 2 ? 13 : delta === 3 ? 8 : 0
  }

  // Data quality: 0–15 pts
  const source = isRealWorld ? 15 : hasModel ? 12 : 4

  // Engine info: 0–10 pts (proxy: known from dataset vs guessed)
  const specs = hasModel ? 10 : data.engine_cc !== 1500 ? 6 : 2

  return { model, year, source, specs }
}

const SEGMENTS = [
  { key: 'model'  as const, label: 'Car Found',    max: 50, color: '#10b981' },
  { key: 'year'   as const, label: 'Year',         max: 25, color: '#3b82f6' },
  { key: 'source' as const, label: 'Data Quality', max: 15, color: '#8b5cf6' },
  { key: 'specs'  as const, label: 'Engine Info',  max: 10, color: '#f59e0b' },
]

export function AccuracyBar({ data, compact = false }: { data: RecommendationResult; compact?: boolean }) {
  const factors  = calcFactors(data)
  const total    = factors.model + factors.year + factors.source + factors.specs
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setReady(false)
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setReady(true)))
    return () => cancelAnimationFrame(id)
  }, [data])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
        <span style={{ fontSize: '0.72rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted-foreground, #6b7280)' }}>
          Result Accuracy
        </span>
        <span style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--foreground, #111827)' }}>
          {total}%
        </span>
      </div>

      {/* Segmented bar — width of each segment reflects its share of the total score */}
      <div style={{ display: 'flex', gap: '2px', height: '8px', borderRadius: '999px', overflow: 'hidden' }}>
        {SEGMENTS.map(seg => (
          <div
            key={seg.key}
            style={{
              width: `${seg.max}%`,
              background: 'var(--muted, #e5e7eb)',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <div style={{
              position: 'absolute', inset: 0,
              width: ready ? `${(factors[seg.key] / seg.max) * 100}%` : '0%',
              background: seg.color,
              transition: 'width 0.7s ease-out',
            }} />
          </div>
        ))}
      </div>

      {/* Factor labels aligned to each segment — hidden in compact mode */}
      {!compact && (
        <div style={{ display: 'flex', gap: '2px', marginTop: '0.3rem' }}>
          {SEGMENTS.map(seg => (
            <div key={seg.key} style={{ width: `${seg.max}%`, textAlign: 'center' }}>
              <span style={{ fontSize: '0.58rem', color: 'var(--muted-foreground, #9ca3af)', whiteSpace: 'nowrap' }}>
                {seg.label}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
