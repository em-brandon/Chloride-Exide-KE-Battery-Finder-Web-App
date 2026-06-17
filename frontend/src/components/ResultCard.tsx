import type { RecommendationResult, BatteryEntry } from '@/types/battery'
import { Badge, techVariant } from '@/components/ui/Badge'
import { AccuracyBar } from '@/components/AccuracyBar'
import { FeedbackModal } from '@/components/FeedbackModal'
import { useState } from 'react'
import { ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { StarIcon, ShoppingBagIcon } from '@heroicons/react/24/outline'
import ReactCountryFlag from 'react-country-flag'
import exideMaxxLogo from '@/assets/exide-max-logo.webp'
import sparkLogo     from '@/assets/spark-logo.webp'
import powerlastLogo from '@/assets/powerlast-logo.webp'
import supremeLogo   from '@/assets/supreme-logo.webp'
import sebangLogo    from '@/assets/sebang-logo.webp'
import exideAgmLogo  from '@/assets/exide-agm-logo.webp'
import sbFloodedLogo from '@/assets/sb-flooded-logo.webp'

function getBrandLogo(code: string): string | null {
  const u = code.toUpperCase()
  if (u.includes('MAXX'))                                    return exideMaxxLogo
  if (u.includes('POWERLAST'))                               return powerlastLogo
  if (u.includes('SPARK'))                                   return sparkLogo
  if (u.includes('SUPREME'))                                 return supremeLogo
  if (u.includes('SEBANG'))                                  return sebangLogo
  if (u.includes('EXIDE') && !u.includes('CHLORIDE EXIDE') && !u.includes('EFB')) return exideAgmLogo
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

      {/* Header — title left, action buttons right */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem' }}>
        <div>
          <h2 className="text-base font-bold text-card-foreground">Battery Recommendation</h2>
          {!isFallback && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {data.matched_make} {data.matched_model} · {data.matched_year}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => setFeedbackOpen(true)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
              background: '#fff', border: '1.5px solid #CC0000', color: '#CC0000',
              borderRadius: 6, padding: '0.3rem 0.9rem',
              fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer',
              fontFamily: 'inherit', transition: 'background 0.15s, color 0.15s',
            }}
            onMouseEnter={e => {
              const b = e.currentTarget as HTMLButtonElement
              b.style.background = '#CC0000'
              b.style.color = '#fff'
            }}
            onMouseLeave={e => {
              const b = e.currentTarget as HTMLButtonElement
              b.style.background = '#fff'
              b.style.color = '#CC0000'
            }}
          >
            <StarIcon style={{ width: 15, height: 15 }} />
            Rate this result
          </button>
          <a
            href="https://www.chlorideexide.com/category/all-products"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
              background: '#CC0000', color: '#fff',
              borderRadius: 6, padding: '0.3rem 0.9rem',
              fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer',
              fontFamily: 'inherit', textDecoration: 'none',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.background = '#990000' }}
            onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.background = '#CC0000' }}
          >
            <ShoppingBagIcon style={{ width: 15, height: 15 }} />
            Shop Now
          </a>
        </div>
      </div>

      {/* Dial a Battery */}
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap',
        gap: '0.4rem 0.9rem',
        background: '#f9fafb',
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        padding: '0.45rem 0.75rem',
        fontSize: '0.72rem',
      }}>
        <span style={{ fontWeight: 700, color: '#374151', whiteSpace: 'nowrap' }}>📞 Dial a Battery</span>
        <span style={{ color: '#d1d5db' }}>·</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
          <ReactCountryFlag countryCode="KE" svg style={{ width: '1.1em', height: '1.1em' }} />
          <span style={{ color: '#CC0000', fontWeight: 600 }}>0719 080 000</span>
        </span>
        <span style={{ color: '#d1d5db' }}>·</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
          <ReactCountryFlag countryCode="TZ" svg style={{ width: '1.1em', height: '1.1em' }} />
          <span style={{ color: '#111827', fontWeight: 600 }}>0677 484 631</span>
        </span>
        <span style={{ color: '#d1d5db' }}>·</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
          <ReactCountryFlag countryCode="UG" svg style={{ width: '1.1em', height: '1.1em' }} />
          <span style={{ color: '#16a34a', fontWeight: 600 }}>0200 400 900</span>
        </span>
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
        {brandLogo && (
          <div className="flex items-center gap-2 pb-1 border-b border-red-100 dark:border-red-900/40">
            <img src={brandLogo} alt="" style={{ height: 28, width: 'auto', maxWidth: 120, objectFit: 'contain' }} />
          </div>
        )}
        <div className="flex items-center gap-0 flex-wrap">
          <Stat label="Ah" value={p.ah} />
          <div className="w-px self-stretch bg-red-200 dark:bg-red-800/40 mx-3" />
          <Stat label="CCA (EN)" value={p.cca_en} />
          <div className="w-px self-stretch bg-red-200 dark:bg-red-800/40 mx-3" />
          <Badge variant={techVariant(p.technology)} className="self-center">
            {p.technology ?? 'MF'}
          </Badge>
        </div>
        <div>
          <div className="font-bold text-base text-card-foreground">{p.battery_code}</div>
          {p.model_key && (
            <div className="text-xs text-muted-foreground mt-0.5">{p.model_key}</div>
          )}
        </div>
      </div>

      {/* Accuracy bar */}
      <AccuracyBar data={data} />

      <FeedbackModal
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        vehicleLabel={vehicleLabel}
        inputType="dropdown"
        matchConfidence={data.confidence}
        matchType={data.match_type}
        recommendedBattery={data.primary?.battery_code ?? undefined}
      />

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
