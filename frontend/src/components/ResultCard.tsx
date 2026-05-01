import type { RecommendationResult, BatteryEntry } from '@/types/battery'
import { Badge, techVariant, matchVariant } from '@/components/ui/Badge'
import { ConfidenceBar } from '@/components/ConfidenceBar'
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

const MATCH_DESCRIPTIONS: Record<string, { color: string; label: string; desc: string }> = {
  exact:    { color: 'text-emerald-600 dark:text-emerald-400', label: 'Exact Match',      desc: 'Your vehicle\'s make, model, and year were found directly in our dataset. Highest confidence result.' },
  close:    { color: 'text-orange-500 dark:text-orange-400',   label: 'Close Match',      desc: 'Your vehicle\'s model was matched approximately using similarity scoring. Verify specs before purchasing.' },
  fallback: { color: 'text-violet-600 dark:text-violet-400',   label: 'Rule-Based Match', desc: 'No exact model found — battery selected using engine size and fuel type rules. Cross-check with your manual.' },
}

function getMatchInfo(matchType: string) {
  const key = matchType.toLowerCase().includes('exact') ? 'exact'
            : matchType.toLowerCase().includes('close') ? 'close'
            : 'fallback'
  return MATCH_DESCRIPTIONS[key]
}

function MatchTooltip({ matchType }: { matchType: string }) {
  const info = getMatchInfo(matchType)
  return (
    <span className="relative group inline-flex items-center">
      <button
        type="button"
        aria-label="Match type explanation"
        className="w-4 h-4 rounded-full border border-muted-foreground/40 text-muted-foreground hover:border-foreground hover:text-foreground transition-colors text-[0.6rem] font-bold leading-none flex items-center justify-center"
      >
        ?
      </button>
      <span className="pointer-events-none absolute bottom-full right-0 mb-2 w-60 rounded-lg border border-border bg-popover px-3 py-2.5 shadow-lg text-xs text-popover-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-50">
        <span className={cn('font-bold block mb-0.5', info.color)}>{info.label}</span>
        {info.desc}
      </span>
    </span>
  )
}

interface ResultCardProps {
  data: RecommendationResult
}

function AltCard({ alt }: { alt: BatteryEntry }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-1.5">
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
  const p = data.primary

  return (
    <div className="mt-5 animate-slide-up rounded-xl border border-border border-l-4 border-l-[#cc0000] bg-card shadow-md p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-lg font-bold text-card-foreground">Primary Recommendation</h2>
        <div className="flex items-center gap-1.5">
          <Badge variant={matchVariant(data.match_type)}>{data.match_type}</Badge>
          <MatchTooltip matchType={data.match_type} />
        </div>
      </div>

      {/* Primary battery */}
      <div className="rounded-lg border border-red-100 bg-red-50 dark:bg-red-950/20 dark:border-red-900/40 p-4 flex items-center gap-4 flex-wrap">
        <Stat label="Ah"       value={p.ah}     />
        <Stat label="CCA (EN)" value={p.cca_en} />
        <Badge variant={techVariant(p.technology)} className="self-start mt-0.5">
          {p.technology ?? 'MF'}
        </Badge>
        <div className="flex-1 min-w-[140px]">
          <div className="font-bold text-base text-card-foreground">{p.battery_code}</div>
          {p.model_key && (
            <div className="text-xs text-muted-foreground mt-0.5">{p.model_key}</div>
          )}
        </div>
      </div>

      {/* Confidence bar */}
      <ConfidenceBar value={data.confidence} />

      {/* Matched vehicle info */}
      <p className="text-center text-xs text-muted-foreground">
        {data.matched_make
          ? `Matched to: ${data.matched_make} ${data.matched_model} (${data.matched_year})`
          : 'No model match — result based on engine size and fuel type only'}
      </p>

      {/* Alternatives */}
      {data.alternatives.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Alternative Options ({data.alternatives.length})
            </span>
            <button
              onClick={() => setAltsVisible(v => !v)}
              className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {altsVisible ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {altsVisible ? 'hide' : 'show'}
            </button>
          </div>
          <div className={cn(
            'grid gap-2',
            'grid-cols-[repeat(auto-fill,minmax(170px,1fr))]',
            !altsVisible && 'hidden'
          )}>
            {data.alternatives.map(alt => (
              <AltCard key={alt.battery_code} alt={alt} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="text-center min-w-[56px]">
      <div className="text-2xl font-extrabold text-[#cc0000]">
        {value != null ? value : '—'}
      </div>
      <div className="text-[0.65rem] text-muted-foreground mt-0.5">{label}</div>
    </div>
  )
}
