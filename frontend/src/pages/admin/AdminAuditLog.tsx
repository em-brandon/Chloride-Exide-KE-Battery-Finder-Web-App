import { useState, useEffect, useCallback, useTransition } from 'react'
import {
  fetchAuditLog,
  fetchAuditUsers,
  type AuditEntry,
  type AuditFilters,
} from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  ClipboardDocumentListIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  DocumentArrowDownIcon,
  TableCellsIcon,
  ArrowUturnLeftIcon,
  FunnelIcon,
  XMarkIcon,
  MagnifyingGlassIcon,
} from '@heroicons/react/20/solid'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R   = '#CC0000'
const RD  = '#990000'
const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}
const INPUT: React.CSSProperties = {
  borderRadius: '8px',
  border: '1px solid var(--adm-input-border)',
  background: 'var(--adm-input-bg)',
  color: 'var(--adm-text-1)',
  padding: '0.4rem 0.7rem',
  fontSize: '0.82rem',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
  outline: 'none',
  boxSizing: 'border-box' as const,
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const secs = Math.floor(diffMs / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return `${Math.floor(days / 30)}mo ago`
}

function countChangedFields(e: AuditEntry): number {
  if (e.action !== 'UPDATE' || !e.old_values || !e.new_values) return 0
  const keys = new Set([...Object.keys(e.old_values), ...Object.keys(e.new_values)])
  let count = 0
  for (const k of keys) {
    if (String(e.old_values[k] ?? '') !== String(e.new_values[k] ?? '')) count++
  }
  return count
}

function batteryCode(e: AuditEntry): string {
  return String(e.new_values?.battery_code ?? e.old_values?.battery_code ?? '—')
}

// ── CSV export ────────────────────────────────────────────────────────────────
function exportCSV(items: AuditEntry[]) {
  const headers = ['ID', 'Action', 'Battery ID', 'Battery Code', 'Changed By', 'When', 'Fields Changed']
  const escape = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const csvRows = items.map(e => [
    e.id, e.action, e.battery_id ?? '', batteryCode(e), e.changed_by,
    new Date(e.changed_at).toLocaleString(),
    e.action === 'UPDATE' ? countChangedFields(e) : '',
  ].map(escape).join(','))
  const csv = [headers.map(escape).join(','), ...csvRows].join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── PDF export ────────────────────────────────────────────────────────────────
function exportPDF(items: AuditEntry[]) {
  const rows = items.map(e => {
    const code = batteryCode(e)
    const changed = e.action === 'UPDATE' ? String(countChangedFields(e)) : '—'
    return `<tr>
      <td>${e.id}</td>
      <td><span class="badge ${e.action}">${e.action}</span></td>
      <td>${e.battery_id ?? '—'}</td>
      <td style="font-family:monospace;font-weight:700">${code}</td>
      <td>${e.changed_by}</td>
      <td>${new Date(e.changed_at).toLocaleString()}</td>
      <td>${changed}</td>
    </tr>`
  }).join('')
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"/>
  <title>Audit Log — Chloride Exide</title>
  <style>
    body{font-family:'Segoe UI',sans-serif;font-size:11px;color:#111;margin:24px}
    h1{color:#CC0000;margin:0 0 4px;font-size:18px}
    p.meta{color:#666;font-size:10px;margin:0 0 16px}
    table{width:100%;border-collapse:collapse}
    th{background:#f4f5f7;font-size:9px;text-transform:uppercase;letter-spacing:.06em;padding:7px 9px;text-align:left;border-bottom:2px solid #ddd;color:#555}
    td{padding:6px 9px;border-bottom:1px solid #eee;vertical-align:middle}
    tr:nth-child(even) td{background:#fafafa}
    .badge{display:inline-block;padding:2px 7px;border-radius:99px;font-size:8px;font-weight:700}
    .INSERT{background:#f0fdf4;color:#15803d}
    .UPDATE{background:#eff6ff;color:#1d4ed8}
    .DELETE{background:#fff5f5;color:#CC0000}
    @media print{@page{margin:1.5cm}body{margin:0}}
  </style></head>
  <body>
    <h1>Chloride Exide — Audit Log</h1>
    <p class="meta">Generated: ${new Date().toLocaleString()} &nbsp;·&nbsp; ${items.length} entries on this page</p>
    <table>
      <thead><tr><th>#</th><th>Action</th><th>Battery ID</th><th>Battery Code</th><th>Changed By</th><th>When</th><th>Fields Changed</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </body></html>`
  const win = window.open('', '_blank', 'width=960,height=720')
  if (!win) { alert('Pop-up blocked — please allow pop-ups for this site.'); return }
  win.document.write(html); win.document.close(); win.focus()
  setTimeout(() => win.print(), 600)
}

// ── Action badge styles ───────────────────────────────────────────────────────
function actionStyle(action: AuditEntry['action']): React.CSSProperties {
  const map: Record<string, React.CSSProperties> = {
    INSERT: { background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0' },
    UPDATE: { background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' },
    DELETE: { background: '#fff5f5', color: R,          border: `1px solid #f5c6c6` },
  }
  return map[action] ?? { background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-2)', border: '1px solid var(--adm-sep)' }
}

// ── Diff viewer ───────────────────────────────────────────────────────────────
function DiffViewer({ old_, new_ }: { old_: Record<string, unknown> | null; new_: Record<string, unknown> | null }) {
  const keys = Array.from(new Set([
    ...Object.keys(old_ ?? {}),
    ...Object.keys(new_ ?? {}),
  ]))
  if (keys.length === 0) return <span style={{ fontSize: '0.75rem', color: 'rgba(107,114,128,0.6)' }}>No field data</span>
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem' }}>
      <thead>
        <tr>
          <th style={{ textAlign: 'left', paddingRight: '1.5rem', paddingBottom: '0.4rem', fontWeight: 700, fontSize: '0.65rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.7)', width: '8rem' }}>Field</th>
          <th style={{ textAlign: 'left', paddingRight: '1.5rem', paddingBottom: '0.4rem', fontWeight: 700, fontSize: '0.65rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.7)' }}>Before</th>
          <th style={{ textAlign: 'left', paddingBottom: '0.4rem', fontWeight: 700, fontSize: '0.65rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.7)' }}>After</th>
        </tr>
      </thead>
      <tbody>
        {keys.map(k => {
          const before  = old_ ? String(old_[k] ?? '') : '—'
          const after   = new_ ? String(new_[k] ?? '') : '—'
          const changed = before !== after
          return (
            <tr key={k}>
              <td style={{ paddingRight: '1.5rem', paddingTop: '0.25rem', fontFamily: 'monospace', color: changed ? 'rgba(17,24,39,0.8)' : 'rgba(107,114,128,0.5)', fontWeight: changed ? 600 : 400 }}>{k}</td>
              <td style={{ paddingRight: '1.5rem', paddingTop: '0.25rem', color: changed ? '#b91c1c' : 'rgba(107,114,128,0.5)', textDecoration: changed ? 'line-through' : 'none' }}>{before}</td>
              <td style={{ paddingTop: '0.25rem', color: changed ? '#15803d' : 'rgba(107,114,128,0.5)', fontWeight: changed ? 600 : 400 }}>{after}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
const ACTIONS = ['INSERT', 'UPDATE', 'DELETE'] as const

type FilterState = {
  actions: Set<string>
  user: string
  batteryCode: string
  dateFrom: string
  dateTo: string
}

const EMPTY_FILTERS: FilterState = { actions: new Set(), user: '', batteryCode: '', dateFrom: '', dateTo: '' }

export default function AdminAuditLog() {
  const [items, setItems]       = useState<AuditEntry[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, startLoad]    = useTransition()
  const [expanded, setExpanded] = useState<number | null>(null)
  const [adminUsers, setAdminUsers] = useState<string[]>([])
  const [pending, setPending]   = useState<FilterState>(EMPTY_FILTERS)
  const [applied, setApplied]   = useState<FilterState>(EMPTY_FILTERS)

  const PAGE_SIZE = 50
  const totalPages = Math.ceil(total / PAGE_SIZE)

  useEffect(() => {
    fetchAuditUsers().then(r => setAdminUsers(r.users)).catch(() => {})
  }, [])

  const load = useCallback(() => {
    const filters: AuditFilters = {}
    if (applied.actions.size > 0) filters.action = [...applied.actions].join(',')
    if (applied.user)        filters.changed_by   = applied.user
    if (applied.batteryCode) filters.battery_code = applied.batteryCode
    if (applied.dateFrom)    filters.date_from    = applied.dateFrom
    if (applied.dateTo)      filters.date_to      = applied.dateTo
    let cancelled = false
    startLoad(async () => {
      const r = await fetchAuditLog(page, PAGE_SIZE, filters)
      if (cancelled) return
      setItems(r.items); setTotal(r.total)
    })
    return () => { cancelled = true }
  }, [page, applied])

  useEffect(() => { load() }, [load])

  function applyFilters() { setPage(1); setApplied({ ...pending, actions: new Set(pending.actions) }) }
  function resetFilters()  { setPending(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1) }
  function toggleAction(a: string) {
    setPending(p => {
      const next = new Set(p.actions)
      if (next.has(a)) { next.delete(a) } else { next.add(a) }
      return { ...p, actions: next }
    })
  }

  const summary = {
    INSERT: items.filter(e => e.action === 'INSERT').length,
    UPDATE: items.filter(e => e.action === 'UPDATE').length,
    DELETE: items.filter(e => e.action === 'DELETE').length,
  }
  const hasFilters = applied.actions.size > 0 || applied.user || applied.batteryCode || applied.dateFrom || applied.dateTo

  return (
    <AdminLayout>

      {/* ── Header ── */}
      <header style={{ background: 'var(--adm-header-bg)', borderBottom: '1px solid var(--adm-sep)', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ClipboardDocumentListIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Audit Log</span>
        </div>
        {hasFilters && <span style={{ fontSize: '0.68rem', fontWeight: 700, background: '#fff5f5', color: R, border: '1px solid #f5c6c6', borderRadius: '99px', padding: '0.15rem 0.6rem' }}>Filtered</span>}
        <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: 'var(--adm-text-2)', background: 'var(--adm-subtle-bg)', borderRadius: '99px', padding: '0.2rem 0.7rem', border: '1px solid var(--adm-sep)' }}>{total.toLocaleString()} entries</span>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          <button onClick={() => exportCSV(items)} title="Export current page as CSV" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.75rem', fontWeight: 600, color: 'var(--adm-text-1)', background: 'var(--adm-card-bg)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.35rem 0.8rem', cursor: 'pointer' }} onMouseEnter={e => { e.currentTarget.style.borderColor = '#1d4ed8'; e.currentTarget.style.color = '#1d4ed8' }} onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e4e9'; e.currentTarget.style.color = 'rgba(17,24,39,0.7)' }}>
            <TableCellsIcon style={{ width: 13, height: 13 }} /> CSV
          </button>
          <button onClick={() => exportPDF(items)} title="Print / Save as PDF" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.75rem', fontWeight: 600, color: '#fff', background: R, border: 'none', borderRadius: '8px', padding: '0.35rem 0.85rem', cursor: 'pointer' }} onMouseEnter={e => (e.currentTarget.style.background = RD)} onMouseLeave={e => (e.currentTarget.style.background = R)}>
            <DocumentArrowDownIcon style={{ width: 13, height: 13 }} /> PDF
          </button>
        </div>
      </header>

      <main style={{ maxWidth: '1080px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>

        {/* ── Filter bar ── */}
        <div style={{ ...CARD, padding: '1.1rem 1.4rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.9rem' }}>
            <FunnelIcon style={{ width: 13, height: 13, color: 'rgba(107,114,128,0.6)' }} />
            <span style={{ fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)' }}>Filters</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.85rem', alignItems: 'flex-end' }}>

            {/* Action toggles */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <label style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.75)' }}>Action</label>
              <div style={{ display: 'flex', gap: '0.35rem' }}>
                {ACTIONS.map(a => {
                  const active = pending.actions.has(a)
                  const s = actionStyle(a as AuditEntry['action'])
                  return (
                    <button key={a} onClick={() => toggleAction(a)} style={{ fontSize: '0.72rem', fontWeight: 700, borderRadius: '99px', padding: '0.25rem 0.75rem', cursor: 'pointer', background: active ? (s.background as string) : '#f4f5f7', color: active ? (s.color as string) : 'rgba(107,114,128,0.7)', border: active ? (s.border as string) : '1px solid #e2e4e9' }}>
                      {a}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Admin user */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <label style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.75)' }}>Changed By</label>
              <select value={pending.user} onChange={e => setPending(p => ({ ...p, user: e.target.value }))} style={{ ...INPUT, minWidth: '140px' }} onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(204,0,0,0.1)' }} onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }}>
                <option value="">All users</option>
                {adminUsers.map(u => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>

            {/* Battery code */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <label style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.75)' }}>Battery Code</label>
              <div style={{ position: 'relative' }}>
                <MagnifyingGlassIcon style={{ width: 13, height: 13, color: 'rgba(107,114,128,0.45)', position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
                <input type="text" placeholder="e.g. NS60L" value={pending.batteryCode} onChange={e => setPending(p => ({ ...p, batteryCode: e.target.value }))} style={{ ...INPUT, paddingLeft: '2rem', minWidth: '130px' }} onKeyDown={e => e.key === 'Enter' && applyFilters()} onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(204,0,0,0.1)' }} onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }} />
              </div>
            </div>

            {/* Date range */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <label style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.75)' }}>Date From</label>
              <input type="date" value={pending.dateFrom} onChange={e => setPending(p => ({ ...p, dateFrom: e.target.value }))} style={{ ...INPUT }} onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(204,0,0,0.1)' }} onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              <label style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.75)' }}>Date To</label>
              <input type="date" value={pending.dateTo} onChange={e => setPending(p => ({ ...p, dateTo: e.target.value }))} style={{ ...INPUT }} onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(204,0,0,0.1)' }} onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }} />
            </div>

            {/* Apply / Reset */}
            <div style={{ display: 'flex', gap: '0.4rem', marginLeft: 'auto' }}>
              {hasFilters && (
                <button onClick={resetFilters} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.78rem', fontWeight: 600, color: 'rgba(107,114,128,0.75)', background: 'var(--adm-subtle-bg)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.42rem 0.9rem', cursor: 'pointer' }}>
                  <XMarkIcon style={{ width: 12, height: 12 }} /> Reset
                </button>
              )}
              <button onClick={applyFilters} style={{ fontSize: '0.78rem', fontWeight: 700, color: '#fff', background: R, border: 'none', borderRadius: '8px', padding: '0.42rem 1.1rem', cursor: 'pointer' }} onMouseEnter={e => (e.currentTarget.style.background = RD)} onMouseLeave={e => (e.currentTarget.style.background = R)}>
                Apply Filters
              </button>
            </div>
          </div>
        </div>

        {/* ── Summary strip ── */}
        {items.length > 0 && (
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              { label: 'Inserts', count: summary.INSERT, bg: '#f0fdf4', color: '#15803d', border: '#bbf7d0' },
              { label: 'Updates', count: summary.UPDATE, bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
              { label: 'Deletes', count: summary.DELETE, bg: '#fff5f5', color: R,          border: '#f5c6c6' },
            ].map(({ label, count, bg, color, border }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: bg, border: `1px solid ${border}`, borderRadius: '8px', padding: '0.4rem 0.85rem', fontSize: '0.78rem' }}>
                <span style={{ fontWeight: 800, color, fontSize: '1rem' }}>{count}</span>
                <span style={{ fontWeight: 600, color }}>{label}</span>
                <span style={{ color, opacity: 0.5, fontSize: '0.68rem' }}>on page</span>
              </div>
            ))}
            <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: 'rgba(107,114,128,0.6)' }}>
              {total.toLocaleString()} total · page {page}{totalPages > 1 ? ` of ${totalPages}` : ''}
            </span>
          </div>
        )}

        {/* ── Table ── */}
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)', borderBottom: '2px solid var(--adm-sep)' }}>
                  {['Action', 'Battery Code', 'Changed By', 'When', 'Fields', ''].map(h => (
                    <th key={h} style={{ padding: '0.75rem 1.1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && <tr><td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>Loading…</td></tr>}
                {!loading && items.length === 0 && <tr><td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>No audit entries found</td></tr>}
                {!loading && items.map((e, i) => {
                  const isExpanded = expanded === e.id
                  const changedCount = countChangedFields(e)
                  const code = batteryCode(e)
                  return (
                    <>
                      <tr key={e.id} style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none', background: isExpanded ? '#fef9f9' : 'var(--adm-card-bg)' }} onMouseEnter={ev => { if (!isExpanded) ev.currentTarget.style.background = 'var(--adm-row-hover)' }} onMouseLeave={ev => { if (!isExpanded) ev.currentTarget.style.background = 'var(--adm-card-bg)' }}>

                        {/* Action badge */}
                        <td style={{ padding: '0.8rem 1.1rem' }}>
                          <span style={{ display: 'inline-block', padding: '0.18rem 0.65rem', borderRadius: '99px', fontSize: '0.7rem', fontWeight: 700, ...actionStyle(e.action) }}>{e.action}</span>
                        </td>

                        {/* Battery code */}
                        <td style={{ padding: '0.8rem 1.1rem' }}>
                          <span style={{ fontFamily: 'monospace', fontWeight: 700, color: R, fontSize: '0.8rem' }}>{code}</span>
                          {e.battery_id && <span style={{ display: 'block', fontSize: '0.65rem', color: 'rgba(107,114,128,0.5)', marginTop: '0.1rem' }}>ID: {e.battery_id}</span>}
                        </td>

                        {/* Changed by */}
                        <td style={{ padding: '0.8rem 1.1rem', fontSize: '0.78rem', color: 'rgba(17,24,39,0.75)' }}>{e.changed_by}</td>

                        {/* When */}
                        <td style={{ padding: '0.8rem 1.1rem', whiteSpace: 'nowrap' }}>
                          <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'rgba(17,24,39,0.7)' }}>{relativeTime(e.changed_at)}</span>
                          <span style={{ display: 'block', fontSize: '0.65rem', color: 'rgba(107,114,128,0.55)', marginTop: '0.1rem' }}>{new Date(e.changed_at).toLocaleString()}</span>
                        </td>

                        {/* Changed fields count */}
                        <td style={{ padding: '0.8rem 1.1rem' }}>
                          {e.action === 'UPDATE' && changedCount > 0
                            ? <span style={{ display: 'inline-block', padding: '0.15rem 0.55rem', borderRadius: '99px', background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', fontSize: '0.7rem', fontWeight: 700 }}>{changedCount} field{changedCount !== 1 ? 's' : ''}</span>
                            : <span style={{ color: 'rgba(107,114,128,0.35)', fontSize: '0.72rem' }}>—</span>}
                        </td>

                        {/* Actions */}
                        <td style={{ padding: '0.8rem 1.1rem' }}>
                          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                            <button onClick={() => setExpanded(isExpanded ? null : e.id)} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.72rem', fontWeight: 600, color: isExpanded ? R : '#1d4ed8', background: isExpanded ? '#fff5f5' : '#eff6ff', border: `1px solid ${isExpanded ? '#f5c6c6' : '#bfdbfe'}`, borderRadius: '6px', padding: '0.22rem 0.6rem', cursor: 'pointer' }}>
                              {isExpanded ? <><ChevronUpIcon style={{ width: 11, height: 11 }} /> Hide</> : <><ChevronDownIcon style={{ width: 11, height: 11 }} /> Diff</>}
                            </button>
                            {e.action === 'DELETE' && (
                              <button onClick={() => alert('Revert functionality is coming soon. This will restore the deleted battery from the audit record.')} title="Restore this deleted battery (coming soon)" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.72rem', fontWeight: 600, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', padding: '0.22rem 0.6rem', cursor: 'pointer' }}>
                                <ArrowUturnLeftIcon style={{ width: 11, height: 11 }} /> Revert
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>

                      {/* Diff row */}
                      {isExpanded && (
                        <tr key={`${e.id}-diff`}>
                          <td colSpan={6} style={{ background: '#fef9f9', borderTop: `2px solid ${R}20`, padding: '1rem 1.5rem' }}>
                            <DiffViewer old_={e.old_values} new_={e.new_values} />
                          </td>
                        </tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Pagination ── */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--adm-text-2)' }}>
            <span>{total.toLocaleString()} total entries</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', fontSize: '0.78rem', fontWeight: 600, cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.4 : 1, color: 'var(--adm-text-1)' }} onMouseEnter={e => { if (page !== 1) { e.currentTarget.style.borderColor = R; e.currentTarget.style.color = R } }} onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--adm-sep)'; e.currentTarget.style.color = 'var(--adm-text-1)' }}>
                <ChevronLeftIcon style={{ width: 13, height: 13 }} /> Prev
              </button>
              <span style={{ padding: '0 0.5rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>{page} / {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', fontSize: '0.78rem', fontWeight: 600, cursor: page === totalPages ? 'not-allowed' : 'pointer', opacity: page === totalPages ? 0.4 : 1, color: 'var(--adm-text-1)' }} onMouseEnter={e => { if (page !== totalPages) { e.currentTarget.style.borderColor = R; e.currentTarget.style.color = R } }} onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--adm-sep)'; e.currentTarget.style.color = 'var(--adm-text-1)' }}>
                Next <ChevronRightIcon style={{ width: 13, height: 13 }} />
              </button>
            </div>
          </div>
        )}
      </main>
    </AdminLayout>
  )
}
