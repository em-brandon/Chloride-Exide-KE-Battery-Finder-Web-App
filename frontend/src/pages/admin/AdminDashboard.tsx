import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  BoltIcon,
  CircleStackIcon,
  SignalIcon,
  BookOpenIcon,
  FunnelIcon,
  ArrowPathIcon,
  ArrowDownTrayIcon,
  ClipboardDocumentListIcon,
  ChevronRightIcon,
  ExclamationCircleIcon,
  CheckCircleIcon,
  GlobeAltIcon,
} from '@heroicons/react/20/solid'
import {
  fetchAdminStats,
  fetchHealthStatus,
  refreshCache,
  exportBatteriesUrl,
  getWebValidateCoverage,
  type AdminStats,
  type MatchBreakdown,
  type HealthStatus,
  type CoverageInfo,
} from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'
import { OrbitLoader } from '@/components/ui/OrbitLoader'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

// ── InfoTooltip ───────────────────────────────────────────────────────────────
function InfoTooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <button
        type="button"
        onMouseEnter={() => { setOpen(true); setHovered(true) }}
        onMouseLeave={() => { setOpen(false); setHovered(false) }}
        aria-label="More info"
        style={{
          width: 14, height: 14, borderRadius: '50%',
          border: `1px solid ${hovered ? R : 'rgba(107,114,128,0.35)'}`,
          background: hovered ? '#fff5f5' : 'var(--adm-card-bg)',
          cursor: 'default',
          fontSize: '0.55rem', fontWeight: 800,
          color: hovered ? R : 'rgba(107,114,128,0.55)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0, padding: 0, lineHeight: 1,
          transition: 'color 0.15s, border-color 0.15s, background 0.15s',
        }}
      >?</button>
      {open && (
        <span style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%',
          transform: 'translateX(-50%)',
          background: 'var(--adm-card-bg)', color: 'var(--adm-text-1)',
          border: '1px solid var(--adm-card-border)',
          fontSize: '0.7rem', lineHeight: 1.45,
          padding: '0.55rem 0.8rem',
          borderRadius: '8px',
          width: '215px', textAlign: 'left',
          boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
          zIndex: 50,
          whiteSpace: 'normal',
          pointerEvents: 'none',
        }}>
          {text}
        </span>
      )}
    </span>
  )
}

// ── BatteryRecordsCard ────────────────────────────────────────────────────────
// Big total up top (unchanged from the plain StatCard this replaces), then a
// Local/Imported origin split as label-right rows, and a technology-mix
// footer line — the two axes admins actually care about when scanning the
// catalogue (where a battery is sourced from, what chemistry it uses).
function BatteryRecordsCard({ stats, icon }: { stats: AdminStats | null; icon: React.ReactNode }) {
  const accentColor = '#CC0000'
  const c = stats?.counts
  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem 1.25rem', display: 'flex', flexDirection: 'column', borderTop: `3px solid ${accentColor}`, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
          Battery Records
        </span>
        <span style={{ color: accentColor }}>{icon}</span>
      </div>
      <span style={{ textAlign: 'center', fontSize: '2.6rem', fontWeight: 900, color: accentColor, lineHeight: 1, letterSpacing: '-0.02em', padding: '0.3rem 0' }}>
        {c?.battery_specs != null ? c.battery_specs.toLocaleString() : '—'}
      </span>
      <span style={{ textAlign: 'center', fontSize: '0.63rem', color: 'var(--adm-text-2)', marginBottom: '0.6rem' }}>active in database</span>

      {c != null && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.62rem', fontWeight: 700, color: 'var(--adm-text-2)' }}>Local</span>
            <span style={{ fontSize: '0.85rem', fontWeight: 800, color: accentColor }}>{c.battery_origin_local.toLocaleString()}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.62rem', fontWeight: 700, color: 'var(--adm-text-2)' }}>Imported</span>
            <span style={{ fontSize: '0.85rem', fontWeight: 800, color: accentColor }}>{c.battery_origin_imported.toLocaleString()}</span>
          </div>
        </div>
      )}

      {c != null && (
        <div style={{ marginTop: '0.75rem', borderTop: `1px solid ${accentColor}22`, paddingTop: '0.6rem', width: '100%' }}>
          <span style={{ fontSize: '0.63rem', color: 'rgba(107,114,128,0.65)', display: 'block', textAlign: 'center' }}>
            {c.battery_tech_mf} MF · {c.battery_tech_efb} EFB · {c.battery_tech_agm} AGM · {c.battery_tech_flooded} Flooded
          </span>
        </div>
      )}
    </div>
  )
}

// ── MakesModelsCard ───────────────────────────────────────────────────────────
// Two entry-count sources side by side (Core Dataset / OEM Fitment), each an
// independent total row count — not a single blended number, since the two
// sources have very different scales and provenance. Footer breaks down the
// distinct make+model pairs for each, the metric the headline used to show.
function MakesModelsCard({ stats, icon }: { stats: AdminStats | null; icon: React.ReactNode }) {
  const accentColor = '#1d4ed8'
  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem 1.25rem', display: 'flex', flexDirection: 'column', borderTop: `3px solid ${accentColor}`, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
          Makes & Models
        </span>
        <span style={{ color: accentColor }}>{icon}</span>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '0.55rem', padding: '0.5rem 0' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.66rem', fontWeight: 700, color: 'var(--adm-text-2)' }}>Core</span>
          <span style={{ fontSize: '1.6rem', fontWeight: 900, color: accentColor, lineHeight: 1, letterSpacing: '-0.02em' }}>
            {stats?.counts.vehicle_years_total != null ? stats.counts.vehicle_years_total.toLocaleString() : '—'}
          </span>
        </div>
        <div style={{ height: 1, background: `${accentColor}22` }} />
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.66rem', fontWeight: 700, color: 'var(--adm-text-2)' }}>OEM Fitment</span>
          <span style={{ fontSize: '1.6rem', fontWeight: 900, color: accentColor, lineHeight: 1, letterSpacing: '-0.02em' }}>
            {stats?.counts.vehicle_years_exide_total != null ? stats.counts.vehicle_years_exide_total.toLocaleString() : '—'}
          </span>
        </div>
        {stats?.counts.vehicle_years_total != null && stats?.counts.vehicle_years_exide_total != null && (
          <>
            <div style={{ height: 1, background: `${accentColor}22` }} />
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
              <span style={{ fontSize: '0.66rem', fontWeight: 700, color: 'var(--adm-text-2)' }}>Total</span>
              <span style={{ fontSize: '1.6rem', fontWeight: 900, color: '#059669', lineHeight: 1, letterSpacing: '-0.02em' }}>
                {(stats.counts.vehicle_years_total + stats.counts.vehicle_years_exide_total).toLocaleString()}
              </span>
            </div>
          </>
        )}
      </div>
      {stats?.counts.vehicle_years != null && (
        <div style={{ marginTop: '0.75rem', borderTop: `1px solid ${accentColor}22`, paddingTop: '0.6rem', width: '100%' }}>
          <span style={{ fontSize: '0.65rem', color: 'rgba(107,114,128,0.65)', display: 'block', textAlign: 'center' }}>
            {stats.counts.vehicle_years.toLocaleString()} core pairs · {stats.counts.vehicle_years_exide_pairs.toLocaleString()} OEM fitment pairs · {stats.counts.vehicles_raw.toLocaleString()} raw records
          </span>
        </div>
      )}
    </div>
  )
}

// ── RecommendCallsCard ────────────────────────────────────────────────────────
function BreakdownRow({ color, label, count, total }: { color: string; label: string; count: number; total: number }) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ fontSize: '0.62rem', color: 'var(--adm-text-3)', width: 54, flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 5, borderRadius: 3, background: 'var(--adm-card-border)', overflow: 'hidden' }}>
        <div style={{ width: `${Math.max(pct, total > 0 ? 2 : 0)}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.4s ease' }} />
      </div>
      <span style={{ fontSize: '0.62rem', fontWeight: 700, color: 'var(--adm-text-2)', width: 28, textAlign: 'right', flexShrink: 0 }}>{total > 0 ? `${pct}%` : '—'}</span>
    </div>
  )
}

function RecommendCallsCard({ dbReads, breakdown }: { dbReads: number | string; breakdown: MatchBreakdown | null | undefined }) {
  const accent = '#7e22ce'
  const bd = breakdown
  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem', display: 'flex', flexDirection: 'column', borderTop: `3px solid ${accent}`, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>Recommend Calls</span>
        <span style={{ color: accent }}><BookOpenIcon style={{ width: 18, height: 18 }} /></span>
      </div>
      <span style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '3.5rem', fontWeight: 900, color: accent, lineHeight: 1, letterSpacing: '-0.02em', padding: '0.5rem 0' }}>
        {typeof dbReads === 'number' ? dbReads.toLocaleString() : dbReads}
      </span>
      <div style={{ marginTop: '0.75rem', borderTop: `1px solid ${accent}22`, paddingTop: '0.6rem', width: '100%' }}>
        <span style={{ fontSize: '0.65rem', color: 'rgba(107,114,128,0.65)', display: 'block', marginBottom: '0.55rem' }}>today's /recommend requests</span>
        <span style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-3)', display: 'block', marginBottom: '0.4rem' }}>Vehicle → Battery</span>
        {bd && bd.total > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <BreakdownRow color="#10b981" label="Matched"   count={bd.matched}  total={bd.total} />
            <BreakdownRow color="#f97316" label="Close"     count={bd.close}    total={bd.total} />
            <BreakdownRow color="#CC0000" label="Estimated" count={bd.fallback} total={bd.total} />
          </div>
        ) : (
          <span style={{ fontSize: '0.62rem', color: 'rgba(107,114,128,0.45)', fontStyle: 'italic' }}>No data yet today</span>
        )}
        <Link
          to="/admin/search-log"
          style={{ display: 'inline-block', marginTop: '0.6rem', fontSize: '0.62rem', fontWeight: 700, color: accent, textDecoration: 'none', letterSpacing: '0.01em' }}
        >
          View log →
        </Link>
      </div>
    </div>
  )
}

// ── DataCoverageTile ──────────────────────────────────────────────────────────
function DataCoverageTile({ stats, coverage }: { stats: AdminStats | null; coverage: CoverageInfo | null }) {
  const accent = '#059669'
  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem', display: 'flex', flexDirection: 'column', borderTop: `3px solid ${accent}`, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.85rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
            Data Coverage
          </span>
          <InfoTooltip text="Inference: Dial-A-Battery sales data used as Layer 0 of the matching engine. Web Validation: vehicle combos with a confirmed battery spec from online research." />
        </div>
        <GlobeAltIcon style={{ width: 15, height: 15, color: accent }} />
      </div>

      {/* Inference section */}
      <div style={{ paddingBottom: '0.75rem', borderBottom: '1px solid #e2e4e922' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.55)', marginBottom: '0.3rem' }}>
          Inference
        </div>
        <div style={{ fontSize: '2rem', fontWeight: 900, color: accent, lineHeight: 1, letterSpacing: '-0.02em' }}>
          {stats?.counts.inference_makes != null
            ? (stats.counts.inference_makes + stats.counts.inference_models).toLocaleString()
            : '—'}
        </div>
        <div style={{ fontSize: '0.63rem', color: 'rgba(107,114,128,0.6)', marginTop: '0.35rem' }}>
          {stats?.counts.inference_records != null
            ? `${stats.counts.inference_records.toLocaleString()} records · ${stats.counts.inference_makes} makes · ${stats.counts.inference_models} models`
            : 'Loading…'}
        </div>
      </div>

      {/* Web Validation section */}
      <div style={{ paddingTop: '0.75rem' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.55)', marginBottom: '0.3rem' }}>
          Web Validation
        </div>
        <div style={{ fontSize: '2rem', fontWeight: 900, color: accent, lineHeight: 1, letterSpacing: '-0.02em' }}>
          {coverage?.pct_matched != null ? `${coverage.pct_matched.toFixed(1)}%` : '—'}
        </div>
        <div style={{ fontSize: '0.63rem', color: 'rgba(107,114,128,0.6)', marginTop: '0.35rem' }}>
          {coverage != null
            ? `${coverage.master_count.toLocaleString()} validated of ${coverage.total.toLocaleString()}`
            : 'Loading…'}
        </div>
      </div>
    </div>
  )
}

// ── SpeedometerGauge ─────────────────────────────────────────────────────────
function SpeedometerGauge({ status }: { status: 'ok' | 'degraded' | 'down' }) {
  const cx = 60, cy = 58, r = 44, sw = 13

  function toXY(deg: number, radius: number) {
    const rad = deg * Math.PI / 180
    return { x: cx + radius * Math.cos(rad), y: cy - radius * Math.sin(rad) }
  }

  // Arc from startDeg to endDeg via the top semicircle (sweep=1 in SVG = screen-clockwise)
  function arcPath(startDeg: number, endDeg: number) {
    const s = toXY(startDeg, r)
    const e = toXY(endDeg, r)
    const large = (startDeg - endDeg) > 180 ? 1 : 0
    return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`
  }

  // Needle position: ok → right (30°), degraded → top (90°), down → left (150°)
  const needleDeg = status === 'ok' ? 30 : status === 'degraded' ? 90 : 150
  const color     = status === 'ok' ? '#22c55e' : status === 'degraded' ? '#f59e0b' : R
  const label     = status === 'ok' ? 'Healthy'  : status === 'degraded' ? 'Degraded' : 'Down'

  const needleTip = toXY(needleDeg, r - sw / 2 - 2)

  return (
    <svg viewBox="0 0 120 78" style={{ width: 130, height: 'auto', display: 'block', margin: '0 auto' }}>
      {/* Background track */}
      <path d={arcPath(180, 0)} fill="none" stroke="#e2e4e9" strokeWidth={sw} strokeLinecap="round" />
      {/* Red zone 180→120 (dim) */}
      <path d={arcPath(180, 120)} fill="none" stroke={R}        strokeWidth={sw} strokeLinecap="round" opacity="0.22" />
      {/* Orange zone 120→60 (dim) */}
      <path d={arcPath(120, 60)}  fill="none" stroke="#f59e0b"  strokeWidth={sw} strokeLinecap="round" opacity="0.22" />
      {/* Green zone 60→0 (dim) */}
      <path d={arcPath(60, 0)}    fill="none" stroke="#22c55e"  strokeWidth={sw} strokeLinecap="round" opacity="0.22" />
      {/* Active arc from left edge up to needle (bright) */}
      <path d={arcPath(180, needleDeg)} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />
      {/* Needle */}
      <line x1={cx} y1={cy} x2={needleTip.x.toFixed(2)} y2={needleTip.y.toFixed(2)} stroke="#1f2937" strokeWidth="3" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="5" fill="#1f2937" />
      <circle cx={cx} cy={cy} r="2.5" fill="#fff" />
      {/* Status label */}
      <text x={cx} y={cy + 17} textAnchor="middle" fontSize="11" fontWeight="800" fill={color} fontFamily="'Segoe UI', system-ui, sans-serif">{label}</text>
    </svg>
  )
}

// ── HealthCard ────────────────────────────────────────────────────────────────
function HealthCard({ status, latency_ms, cluster_connections, max_connections, cluster_usage_pct, pool_size, pool_checked_out, pool_usage_pct }: HealthStatus) {
  const borderColor = status === 'ok' ? '#22c55e' : status === 'degraded' ? '#f59e0b' : R
  const hasClusterStats = cluster_connections !== null && max_connections !== null && cluster_usage_pct !== null
  const usagePct = hasClusterStats
    ? cluster_usage_pct!
    : (pool_usage_pct ?? (pool_size ? Math.round((pool_checked_out / pool_size) * 100) : 0))

  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', borderTop: `3px solid ${borderColor}`, height: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
          Database Health
        </span>
        <SignalIcon style={{ width: 15, height: 15, color: 'rgba(107,114,128,0.5)' }} />
      </div>

      <SpeedometerGauge status={status} />

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--adm-text-2)' }}>
        <span>Latency</span>
        <span style={{ fontWeight: 600, color: latency_ms !== null && latency_ms > 200 ? R : 'rgba(17,24,39,0.7)' }}>
          {latency_ms !== null ? `${latency_ms} ms` : 'n/a'}
        </span>
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--adm-text-2)', marginBottom: '0.3rem' }}>
          <span>Connections (cluster-wide)</span>
          <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'rgba(17,24,39,0.7)' }}>
            {hasClusterStats ? `${cluster_connections} / ${max_connections} (${usagePct}%)` : `${pool_checked_out} / ${pool_size} (${usagePct}%)`}
          </span>
        </div>
        <div style={{ height: 6, borderRadius: 99, background: 'var(--adm-sep)', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${Math.min(usagePct, 100)}%`, background: usagePct > 80 ? R : usagePct > 50 ? '#f59e0b' : '#22c55e', borderRadius: 99, transition: 'width 0.6s ease' }} />
        </div>
        {hasClusterStats && (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.62rem', color: 'var(--adm-text-3)', marginTop: '0.3rem' }}>
            <span>this instance</span>
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{pool_checked_out} / {pool_size} ({pool_usage_pct}%)</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── ActionCard ────────────────────────────────────────────────────────────────
function ActionCard({ icon, label, desc, onClick, href, download, primary, loading }: {
  icon: React.ReactNode; label: string; desc: string;
  onClick?: () => void; href?: string; download?: boolean; primary?: boolean; loading?: boolean
}) {
  const base: React.CSSProperties = {
    ...CARD,
    padding: '1rem 1.2rem',
    display: 'flex', alignItems: 'center', gap: '1rem',
    textDecoration: 'none', cursor: loading ? 'default' : 'pointer', border: '1px solid var(--adm-card-border)',
    width: '100%', textAlign: 'left',
    borderLeft: `4px solid ${primary ? R : 'var(--adm-card-border)'}`,
    transition: 'box-shadow 0.15s, border-color 0.15s',
    background: 'var(--adm-card-bg)',
    opacity: loading ? 0.7 : 1,
  }
  const iconWrap: React.CSSProperties = {
    width: 38, height: 38, borderRadius: 10, background: primary ? '#fff5f5' : 'var(--adm-subtle-bg)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  }
  const content = (
    <>
      <span style={iconWrap}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: primary ? R : 'var(--adm-text-1)' }}>{label}</div>
        <div style={{ fontSize: '0.72rem', color: 'var(--adm-text-2)', marginTop: '0.1rem' }}>
          {loading ? 'Refreshing…' : desc}
        </div>
      </div>
      {loading
        ? <ArrowPathIcon style={{ width: 16, height: 16, color: R, animation: 'spin 0.8s linear infinite' }} />
        : <ChevronRightIcon style={{ width: 16, height: 16, color: 'rgba(107,114,128,0.4)' }} />
      }
    </>
  )
  const hover = (e: React.MouseEvent<HTMLAnchorElement | HTMLButtonElement>) => {
    if (loading) return
    e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.12)'
    e.currentTarget.style.borderLeftColor = R
  }
  const unhover = (e: React.MouseEvent<HTMLAnchorElement | HTMLButtonElement>) => {
    if (loading) return
    e.currentTarget.style.boxShadow = 'var(--adm-card-shadow)'
    e.currentTarget.style.borderLeftColor = primary ? R : 'var(--adm-card-border)'
  }
  if (href) return <a href={href} download={download} style={base} onMouseEnter={hover} onMouseLeave={unhover}>{content}</a>
  return <button onClick={loading ? undefined : onClick} style={base} onMouseEnter={hover} onMouseLeave={unhover}>{content}</button>
}

// ── Animation helper ─────────────────────────────────────────────────────────
function cardAnim(delayMs: number, fillHeight = false): React.CSSProperties {
  return {
    animationName: 'admCardIn',
    animationDuration: '0.48s',
    animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
    animationFillMode: 'both',
    animationDelay: `${delayMs}ms`,
    ...(fillHeight ? { height: '100%' } : {}),
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [stats,    setStats]    = useState<AdminStats | null>(null)
  const [health,   setHealth]   = useState<HealthStatus | null>(null)
  const [coverage, setCoverage] = useState<CoverageInfo | null>(null)
  const [loadErr,  setLoadErr]  = useState<string | null>(null)
  const [cacheMsg, setCacheMsg]           = useState<{ text: string; ok: boolean } | null>(null)
  const [cacheRefreshing, setCacheRefreshing] = useState(false)
  const [loading,  setLoading]  = useState(true)

  const load = useCallback(async () => {
    try {
      const [s, h, cov] = await Promise.all([fetchAdminStats(), fetchHealthStatus(), getWebValidateCoverage()])
      setStats(s); setHealth(h); setCoverage(cov)
    } catch (err) {
      setLoadErr(err instanceof Error ? err.message : 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15 * 60 * 1_000)

    // Force a full reload at midnight to reset daily counters
    const now = new Date()
    const nextMidnight = new Date(now)
    nextMidnight.setHours(24, 0, 0, 0)
    const msUntilMidnight = nextMidnight.getTime() - now.getTime()

    let midnightInterval: ReturnType<typeof setInterval>
    const midnightTimeout = setTimeout(() => {
      load()
      // Then reload every 24 h from that point
      midnightInterval = setInterval(load, 24 * 60 * 60 * 1_000)
    }, msUntilMidnight)

    return () => {
      clearInterval(t)
      clearTimeout(midnightTimeout)
      clearInterval(midnightInterval)
    }
  }, [load])

  async function handleCacheRefresh() {
    setCacheMsg(null)
    setCacheRefreshing(true)
    try {
      await refreshCache()
      setCacheMsg({ text: 'Matcher cache refreshed successfully', ok: true })
    } catch {
      setCacheMsg({ text: 'Cache refresh failed', ok: false })
    } finally {
      setCacheRefreshing(false)
      setTimeout(() => setCacheMsg(null), 4000)
    }
  }

  return (
    <AdminLayout>

      {loading && (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <OrbitLoader gradientId="ce-ringC" />
        </div>
      )}

      {!loading && (
        <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>

          {loadErr && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderRadius: '10px', background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
              <ExclamationCircleIcon style={{ width: 15, height: 15 }} /> {loadErr}
            </div>
          )}

          {/* ── Welcome strip ── */}
          <div style={{ ...cardAnim(0) }}>
          <div style={{ ...CARD, padding: '1.25rem 1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem', borderLeft: `5px solid ${R}` }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--adm-text-1)' }}>Welcome back</div>
              <div style={{ fontSize: '0.78rem', color: 'var(--adm-text-2)', marginTop: '0.2rem' }}>
                Dashboard auto-refreshes every 15 minutes.
                {stats && <> Last loaded: <strong>{new Date().toLocaleTimeString()}</strong></>}
              </div>
            </div>
            <button
              onClick={load}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, color: R, background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer' }}
            >
              <ArrowPathIcon style={{ width: 13, height: 13 }} /> Refresh now
            </button>
          </div>
          </div>

          {/* ── Stat cards — all five in one row ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem' }}>
            <div style={cardAnim(80, true)}><MakesModelsCard stats={stats} icon={<CircleStackIcon style={{ width: 18, height: 18 }} />} /></div>
            <div style={cardAnim(160, true)}><BatteryRecordsCard stats={stats} icon={<BoltIcon style={{ width: 18, height: 18 }} />} /></div>
            <div style={cardAnim(240, true)}><RecommendCallsCard dbReads={stats?.db_reads ?? '—'} breakdown={stats?.match_breakdown} /></div>
            <div style={cardAnim(320, true)}><DataCoverageTile stats={stats} coverage={coverage} /></div>
            {health && <div style={cardAnim(400, true)}><HealthCard {...health} /></div>}
          </div>

          {/* ── Quick actions ── */}
          <div>
            <h2 style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-2)', marginBottom: '0.75rem', ...cardAnim(460) }}>
              Quick Actions
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem' }}>
              <div style={cardAnim(510)}><ActionCard primary
                icon={<BoltIcon style={{ width: 18, height: 18, color: R }} />}
                label="Manage Batteries"
                desc="Add, edit, delete or bulk-upload battery records"
                href="/admin/batteries?manage=true"
              /></div>
              <div style={cardAnim(560)}><ActionCard
                icon={<ArrowDownTrayIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
                label="Export Dataset"
                desc="Download the full battery dataset as .xlsx"
                href={exportBatteriesUrl()}
                download
              /></div>
              <div style={cardAnim(610)}><ActionCard
                icon={<ArrowPathIcon style={{ width: 18, height: 18, color: cacheRefreshing ? R : 'rgba(107,114,128,0.7)' }} />}
                label="Refresh Matcher Cache"
                desc="Force-reload the in-memory vehicle-to-battery matcher"
                onClick={handleCacheRefresh}
                loading={cacheRefreshing}
              /></div>
              <div style={cardAnim(660)}><ActionCard
                icon={<ClipboardDocumentListIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
                label="View Audit Log"
                desc="Browse change history and field-level diffs"
                href="/admin/audit"
              /></div>
              <div style={cardAnim(710)}><ActionCard
                icon={<FunnelIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
                label="Data Pipeline"
                desc="Clean and normalise CRSP and NTSA vehicle datasets"
                href="/admin/pipeline"
              /></div>
            </div>

          </div>

        </main>
      )}

      {/* ── Cache refresh toast ── */}
      {cacheMsg && (
        <div style={{
          position: 'fixed', top: '1.25rem', right: '1.25rem', zIndex: 9999,
          display: 'flex', alignItems: 'center', gap: '0.5rem',
          padding: '0.65rem 1rem',
          background: cacheMsg.ok ? '#f0fdf4' : '#fff5f5',
          border: `1px solid ${cacheMsg.ok ? '#bbf7d0' : '#f5c6c6'}`,
          borderRadius: '10px',
          boxShadow: '0 4px 24px rgba(0,0,0,0.12)',
          fontSize: '0.82rem', fontWeight: 600,
          color: cacheMsg.ok ? '#15803d' : R,
          animation: 'toastIn 0.2s ease',
        }}>
          {cacheMsg.ok
            ? <CheckCircleIcon style={{ width: 15, height: 15, flexShrink: 0 }} />
            : <ExclamationCircleIcon style={{ width: 15, height: 15, flexShrink: 0 }} />
          }
          {cacheMsg.text}
        </div>
      )}
    </AdminLayout>
  )
}

