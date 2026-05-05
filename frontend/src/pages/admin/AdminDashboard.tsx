import { useEffect, useState, useCallback } from 'react'
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
} from '@heroicons/react/20/solid'
import {
  fetchAdminStats,
  fetchHealthStatus,
  refreshCache,
  exportBatteriesUrl,
  type AdminStats,
  type HealthStatus,
} from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

// ── StatCard ──────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, accentColor, icon }: {
  label: string; value: string | number; sub?: string; accentColor?: string
  icon: React.ReactNode
}) {
  const color = accentColor ?? 'rgba(17,24,39,0.88)'
  const borderColor = accentColor ?? '#e2e4e9'
  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem 1.25rem', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', borderTop: `3px solid ${borderColor}` }}>
      {/* Label + icon pinned to top */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.9)' }}>
          {label}
        </span>
        <span style={{ color }}>{icon}</span>
      </div>
      {/* Big number — grows to fill available space */}
      <span style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '3.5rem', fontWeight: 900, color, lineHeight: 1, letterSpacing: '-0.02em', padding: '0.5rem 0' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </span>
      {/* Sub text pinned to footer */}
      {sub && (
        <div style={{ marginTop: '0.75rem', borderTop: `1px solid ${borderColor}22`, paddingTop: '0.6rem', width: '100%' }}>
          <span style={{ fontSize: '0.65rem', color: 'rgba(107,114,128,0.65)', display: 'block' }}>{sub}</span>
        </div>
      )}
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
function HealthCard({ status, latency_ms, pool_size, pool_checked_out, pool_usage_pct }: HealthStatus) {
  const borderColor = status === 'ok' ? '#22c55e' : status === 'degraded' ? '#f59e0b' : R
  const usagePct = pool_usage_pct ?? (pool_size ? Math.round((pool_checked_out / pool_size) * 100) : 0)

  return (
    <div style={{ ...CARD, padding: '1.25rem 1.4rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', borderTop: `3px solid ${borderColor}` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.9)' }}>
          Database Health
        </span>
        <SignalIcon style={{ width: 15, height: 15, color: 'rgba(107,114,128,0.5)' }} />
      </div>

      <SpeedometerGauge status={status} />

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'rgba(107,114,128,0.8)' }}>
        <span>Latency</span>
        <span style={{ fontWeight: 600, color: latency_ms !== null && latency_ms > 200 ? R : 'rgba(17,24,39,0.7)' }}>
          {latency_ms !== null ? `${latency_ms} ms` : 'n/a'}
        </span>
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'rgba(107,114,128,0.8)', marginBottom: '0.3rem' }}>
          <span>Connection pool</span>
          <span>{pool_checked_out} / {pool_size} ({usagePct}%)</span>
        </div>
        <div style={{ height: 6, borderRadius: 99, background: '#e2e4e9', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${Math.min(usagePct, 100)}%`, background: usagePct > 80 ? R : usagePct > 50 ? '#f59e0b' : '#22c55e', borderRadius: 99, transition: 'width 0.6s ease' }} />
        </div>
      </div>
    </div>
  )
}

// ── ActionCard ────────────────────────────────────────────────────────────────
function ActionCard({ icon, label, desc, onClick, href, download, primary }: {
  icon: React.ReactNode; label: string; desc: string;
  onClick?: () => void; href?: string; download?: boolean; primary?: boolean
}) {
  const base: React.CSSProperties = {
    ...CARD,
    padding: '1rem 1.2rem',
    display: 'flex', alignItems: 'center', gap: '1rem',
    textDecoration: 'none', cursor: 'pointer', border: '1px solid #e2e4e9',
    width: '100%', textAlign: 'left',
    borderLeft: `4px solid ${primary ? R : '#e2e4e9'}`,
    transition: 'box-shadow 0.15s, border-color 0.15s',
    background: '#fff',
  }
  const iconWrap: React.CSSProperties = {
    width: 38, height: 38, borderRadius: 10, background: primary ? '#fff5f5' : '#f4f5f7',
    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  }
  const content = (
    <>
      <span style={iconWrap}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '0.85rem', fontWeight: 700, color: primary ? R : 'rgba(17,24,39,0.88)' }}>{label}</div>
        <div style={{ fontSize: '0.72rem', color: 'rgba(107,114,128,0.8)', marginTop: '0.1rem' }}>{desc}</div>
      </div>
      <ChevronRightIcon style={{ width: 16, height: 16, color: 'rgba(107,114,128,0.4)' }} />
    </>
  )
  const hover = (e: React.MouseEvent<HTMLAnchorElement | HTMLButtonElement>) => {
    e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.12)'
    e.currentTarget.style.borderLeftColor = R
  }
  const unhover = (e: React.MouseEvent<HTMLAnchorElement | HTMLButtonElement>) => {
    e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.07)'
    e.currentTarget.style.borderLeftColor = primary ? R : '#e2e4e9'
  }
  if (href) return <a href={href} download={download} style={base} onMouseEnter={hover} onMouseLeave={unhover}>{content}</a>
  return <button onClick={onClick} style={base} onMouseEnter={hover} onMouseLeave={unhover}>{content}</button>
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [stats,    setStats]    = useState<AdminStats | null>(null)
  const [health,   setHealth]   = useState<HealthStatus | null>(null)
  const [loadErr,  setLoadErr]  = useState<string | null>(null)
  const [cacheMsg, setCacheMsg] = useState<{ text: string; ok: boolean } | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([fetchAdminStats(), fetchHealthStatus()])
      setStats(s); setHealth(h)
    } catch (err) {
      setLoadErr(err instanceof Error ? err.message : 'Failed to load dashboard')
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 30_000)
    return () => clearInterval(t)
  }, [load])

  async function handleCacheRefresh() {
    setCacheMsg(null)
    try {
      await refreshCache()
      setCacheMsg({ text: 'Matcher cache refreshed successfully', ok: true })
    } catch {
      setCacheMsg({ text: 'Cache refresh failed', ok: false })
    }
    setTimeout(() => setCacheMsg(null), 4000)
  }

  return (
    <AdminLayout>

      <main style={{ maxWidth: '960px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>

        {loadErr && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderRadius: '10px', background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
            <ExclamationCircleIcon style={{ width: 15, height: 15 }} /> {loadErr}
          </div>
        )}

        {/* ── Welcome strip ── */}
        <div style={{ ...CARD, padding: '1.25rem 1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem', borderLeft: `5px solid ${R}` }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'rgba(17,24,39,0.88)' }}>Welcome back</div>
            <div style={{ fontSize: '0.78rem', color: 'rgba(107,114,128,0.85)', marginTop: '0.2rem' }}>
              Dashboard auto-refreshes every 30 seconds.
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

        {/* ── Stat cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '1rem' }}>
          <StatCard accentColor="#CC0000" label="Battery Records" value={stats?.counts.battery_specs ?? '—'} sub="active in database"     icon={<BoltIcon style={{ width: 18, height: 18 }} />} />
          <StatCard accentColor="#1d4ed8" label="Makes &amp; Models"   value={stats?.counts.vehicle_years  ?? '—'} sub="unique make/model pairs" icon={<CircleStackIcon style={{ width: 18, height: 18 }} />} />
          <StatCard accentColor="#7e22ce" label="API Reads"         value={stats?.db_reads              ?? '—'} sub="cumulative GET requests" icon={<BookOpenIcon style={{ width: 18, height: 18 }} />} />
          {health && <HealthCard {...health} />}
        </div>

        {/* ── Quick actions ── */}
        <div>
          <h2 style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', marginBottom: '0.75rem' }}>
            Quick Actions
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem' }}>
            <ActionCard primary
              icon={<BoltIcon style={{ width: 18, height: 18, color: R }} />}
              label="Manage Batteries"
              desc="Add, edit, delete or bulk-upload battery records"
              href="/admin/batteries?manage=true"
            />
            <ActionCard
              icon={<ArrowDownTrayIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
              label="Export Dataset"
              desc="Download the full battery dataset as .xlsx"
              href={exportBatteriesUrl()}
              download
            />
            <ActionCard
              icon={<ArrowPathIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
              label="Refresh Matcher Cache"
              desc="Force-reload the in-memory vehicle-to-battery matcher"
              onClick={handleCacheRefresh}
            />
            <ActionCard
              icon={<ClipboardDocumentListIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
              label="View Audit Log"
              desc="Browse change history and field-level diffs"
              href="/admin/audit"
            />
            <ActionCard
              icon={<FunnelIcon style={{ width: 18, height: 18, color: 'rgba(107,114,128,0.7)' }} />}
              label="Data Pipeline"
              desc="Clean and normalise CRSP and NTSA vehicle datasets"
              href="/admin/pipeline"
            />
          </div>

          {cacheMsg && (
            <div style={{ marginTop: '0.65rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', fontWeight: 600, color: cacheMsg.ok ? '#15803d' : R, padding: '0.45rem 0.85rem', background: cacheMsg.ok ? '#f0fdf4' : '#fff5f5', border: `1px solid ${cacheMsg.ok ? '#bbf7d0' : '#f5c6c6'}`, borderRadius: '8px' }}>
              {cacheMsg.ok ? <CheckCircleIcon style={{ width: 14, height: 14 }} /> : <ExclamationCircleIcon style={{ width: 14, height: 14 }} />}
              {cacheMsg.text}
            </div>
          )}
        </div>

      </main>
    </AdminLayout>
  )
}

