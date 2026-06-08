import type { RecommendationResult, BatteryEntry } from '@/types/battery'
import { Badge, techVariant } from '@/components/ui/Badge'
import { AccuracyBar } from '@/components/AccuracyBar'
import { FeedbackModal } from '@/components/FeedbackModal'
import { useState } from 'react'
import { ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { ChatBubbleLeftEllipsisIcon } from '@heroicons/react/24/outline'
import exideMaxxLogo from '@/assets/exide-max-logo.png'
import sparkLogo     from '@/assets/spark-logo.jpg'
import powerlastLogo from '@/assets/powerlast-logo.jpg'
import supremeLogo   from '@/assets/supreme-logo.jpg'
import sebangLogo    from '@/assets/sebang-logo.jpg'
import exideAgmLogo  from '@/assets/exide-agm-logo.jpg'
import sbFloodedLogo from '@/assets/sb-flooded-logo.jpg'

function getBrandLogo(code: string): string | null {
  const u = code.toUpperCase()
  if (u.includes('MAXX'))                                    return exideMaxxLogo
  if (u.includes('POWERLAST'))                               return powerlastLogo
  if (u.includes('SPARK'))                                   return sparkLogo
  if (u.includes('SUPREME'))                                 return supremeLogo
  if (u.includes('SEBANG'))                                  return sebangLogo
  if (u.includes('EXIDE') && !u.includes('CHLORIDE EXIDE')) return exideAgmLogo
  if (u.includes('CHLORIDE EXIDE'))                          return sbFloodedLogo
  return null
}

interface ResultCardProps {
  data: RecommendationResult
}

function AltCard({ alt }: { alt: BatteryEntry }) {
  return (
    <div className="shrink-0 w-44 rounded-lg border border-border bg-card p-3 space-y-1.5">
      <div className="font-bold text-sm text-card-foreground">{alt.battery_code}</div>
      <div className="text-xs text-muted-foreground">
        {alt.ah != null ? `${alt.ah} Ah` : ''}
        {alt.cca_en != null ? ` · ${alt.cca_en} CCA` : ''}
      </div>
      <Badge variant={techVariant(alt.technology)} className="text-[0.65rem] mt-1">
        {alt.technology ?? 'MF'}
      </Badge>
    </div>
  )
}

export function ResultCard({ data }: ResultCardProps) {
  const [altsVisible, setAltsVisible] = useState(true)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const p = data.primary
  const brandLogo = getBrandLogo(p.battery_code)
  const isFallback = !data.matched_make
  const vehicleLabel = data.matched_make
    ? `${data.matched_make} ${data.matched_model} (${data.matched_year})`
    : `${data.make} ${data.model} ${data.year}`

  const sameTeachAlts = data.alternatives.filter(
    alt => (alt.technology ?? 'MF') === (p.technology ?? 'MF')
  )

  return (
    <div className="mt-5 animate-slide-up rounded-xl border border-border border-l-4 [border-left-color:#1A35C0] bg-card shadow-md p-4 space-y-3">
      {/* Header */}
      <div>
        <h2 className="text-base font-bold text-card-foreground">Battery Recommendation</h2>
        {!isFallback && (
          <p className="text-sm text-muted-foreground mt-0.5">
            {data.matched_make} {data.matched_model} · {data.matched_year}
          </p>
        )}
      </div>

      {/* Fallback warning — only shown when no model was matched */}
      {isFallback && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-900/40 dark:bg-amber-950/20 px-3 py-2.5">
          <AlertTriangle size={15} className="text-amber-500 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-800 dark:text-amber-300">
            Your exact model wasn't found in our records. This is an estimate based on your{' '}
            {data.engine_cc}cc {data.fuel_type?.toLowerCase()} engine — confirm with a mechanic before purchasing.
          </p>
        </div>
      )}

      {/* Primary battery */}
      <div className="rounded-lg border border-red-100 bg-red-50 dark:bg-red-950/20 dark:border-red-900/40 p-3 space-y-2.5">
        {/* Series logo */}
        {brandLogo && (
          <div className="flex items-center gap-2 pb-1 border-b border-red-100 dark:border-red-900/40">
            <img src={brandLogo} alt="" style={{ height: 28, width: 'auto', maxWidth: 120, objectFit: 'contain' }} />
          </div>
        )}
        {/* Specs row */}
        <div className="flex items-center gap-0 flex-wrap">
          <Stat label="Ah" value={p.ah} />
          <div className="w-px self-stretch bg-red-200 dark:bg-red-800/40 mx-3" />
          <Stat label="CCA (EN)" value={p.cca_en} />
          <div className="w-px self-stretch bg-red-200 dark:bg-red-800/40 mx-3" />
          <Badge variant={techVariant(p.technology)} className="self-center">
            {p.technology ?? 'MF'}
          </Badge>
        </div>
        {/* Battery name */}
        <div>
          <div className="font-bold text-base text-card-foreground">{p.battery_code}</div>
          {p.model_key && (
            <div className="text-xs text-muted-foreground mt-0.5">{p.model_key}</div>
          )}
        </div>
      </div>

      {/* Accuracy bar */}
      <AccuracyBar data={data} />

      {/* Alternatives — same technology only, horizontal scrolling row */}
      {sameTeachAlts.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Same-Technology Alternatives ({sameTeachAlts.length})
            </span>
            <button
              onClick={() => setAltsVisible(v => !v)}
              className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {altsVisible ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {altsVisible ? 'hide' : 'show'}
            </button>
          </div>
          {altsVisible && (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {sameTeachAlts.map(alt => (
                <AltCard key={alt.battery_code} alt={alt} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Feedback trigger */}
      <div className="flex justify-center pt-2 pb-1">
        <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
          {/* Pulse ring */}
          <span style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '999px',
            background: 'rgba(204,0,0,0.18)',
            animation: 'ratePulse 1.8s ease-out infinite',
            pointerEvents: 'none',
          }} />
          <button
            type="button"
            onClick={() => setFeedbackOpen(true)}
            className="group inline-flex items-center gap-2 text-white active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            style={{
              position: 'relative',
              background: '#CC0000',
              boxShadow: '0 3px 12px rgba(204,0,0,0.45)',
              borderRadius: '999px',
              padding: '0.6rem 1.5rem',
              fontSize: '0.95rem',
              fontWeight: 700,
              letterSpacing: '0.01em',
              border: 'none',
              cursor: 'pointer',
              transition: 'background 0.15s, box-shadow 0.15s, transform 0.1s',
              fontFamily: 'inherit',
            }}
            onMouseEnter={e => {
              const b = e.currentTarget as HTMLButtonElement
              b.style.background = '#990000'
              b.style.boxShadow = '0 6px 20px rgba(204,0,0,0.55)'
            }}
            onMouseLeave={e => {
              const b = e.currentTarget as HTMLButtonElement
              b.style.background = '#CC0000'
              b.style.boxShadow = '0 3px 12px rgba(204,0,0,0.45)'
            }}
          >
            <ChatBubbleLeftEllipsisIcon className="w-5 h-5 transition-transform duration-150 group-hover:scale-110" />
            Rate this result
          </button>
        </div>
      </div>

      <FeedbackModal
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        vehicleLabel={vehicleLabel}
        inputType="dropdown"
        matchConfidence={data.confidence}
        matchType={data.match_type}
        recommendedBattery={data.primary?.battery_code ?? undefined}
      />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="text-center min-w-14">
      <div className="text-2xl font-extrabold text-brand">
        {value != null ? value : '—'}
      </div>
      <div className="text-xs font-medium text-muted-foreground mt-0.5">{label}</div>
    </div>
  )
}
// CANARY_TEST_12345
