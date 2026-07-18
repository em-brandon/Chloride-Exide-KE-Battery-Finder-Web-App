import { useState, useEffect, useCallback } from 'react'
import { fetchSearchEvents, type SearchEventEntry } from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  MagnifyingGlassIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  InformationCircleIcon,
  DocumentArrowDownIcon,
} from '@heroicons/react/20/solid'

const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

const MATCH_TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  'Exact Match':           { bg: '#dcfce7', text: '#15803d', border: '#86efac' },
  'Web-Validated Match':   { bg: '#dcfce7', text: '#15803d', border: '#86efac' },
  'Real-World Data Match': { bg: '#dcfce7', text: '#15803d', border: '#86efac' },
  'Close Match':           { bg: '#fff7ed', text: '#c2410c', border: '#fdba74' },
  'Estimated (Rule-Based)':{ bg: '#fff5f5', text: '#CC0000', border: '#fca5a5' },
}

const INPUT_TYPE_LABELS: Record<string, string> = { type: 'Typed', select: 'Selected' }
const INPUT_TYPE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  type:   { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  select: { bg: '#f3f4f6', text: '#374151', border: '#d1d5db' },
}

const PAGE_SIZE = 50

function Dash() {
  return <span style={{ color: 'var(--adm-text-3)' }}>—</span>
}

function MatchTypeBadge({ value }: { value: string | null }) {
  if (!value) return <Dash />
  const c = MATCH_TYPE_COLORS[value] ?? { bg: '#f3f4f6', text: '#374151', border: '#d1d5db' }
  return (
    <span style={{
      display: 'inline-block', padding: '0.15rem 0.55rem', borderRadius: '999px',
      fontSize: '0.7rem', fontWeight: 700,
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
      whiteSpace: 'nowrap',
    }}>
      {value}
    </span>
  )
}

function InputTypeBadge({ value }: { value: string | null }) {
  if (!value) return <Dash />
  const c = INPUT_TYPE_COLORS[value] ?? { bg: '#f3f4f6', text: '#374151', border: '#d1d5db' }
  return (
    <span style={{
      display: 'inline-block', padding: '0.15rem 0.55rem', borderRadius: '999px',
      fontSize: '0.7rem', fontWeight: 700,
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
      whiteSpace: 'nowrap',
    }}>
      {INPUT_TYPE_LABELS[value] ?? value}
    </span>
  )
}

function ConfidenceBar({ value }: { value: number | null }) {
  if (value === null) return <Dash />
  const color = value >= 85 ? '#10b981' : value >= 55 ? '#f97316' : '#CC0000'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
      <div style={{ width: 40, height: 5, borderRadius: 3, background: 'var(--adm-card-border)', overflow: 'hidden', flexShrink: 0 }}>
        <div style={{ width: `${value}%`, height: '100%', borderRadius: 3, background: color }} />
      </div>
      <span style={{ fontSize: '0.72rem', fontWeight: 700, color }}>{value}%</span>
    </span>
  )
}

function fmt(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const TH: React.CSSProperties = {
  padding: '0.75rem 0.85rem',
  textAlign: 'left',
  fontSize: '0.65rem',
  fontWeight: 700,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'var(--adm-text-3)',
  whiteSpace: 'nowrap',
  borderBottom: '2px solid var(--adm-card-border)',
}
const TD: React.CSSProperties = {
  padding: '0.55rem 0.85rem',
  fontSize: '0.78rem',
  color: 'var(--adm-text-2)',
  verticalAlign: 'middle',
}

export default function AdminSearchLog() {
  const [items, setItems]         = useState<SearchEventEntry[]>([])
  const [total, setTotal]         = useState(0)
  const [page, setPage]           = useState(1)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)

  async function generatePdf() {
    setPdfLoading(true)
    try {
      const res = await fetchSearchEvents(1, total || 10000)
      const { default: jsPDF } = await import('jspdf')
      const { default: autoTable } = await import('jspdf-autotable')
      const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })

      const now = new Date()
      const dateStr = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
      const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

      doc.setFontSize(14)
      doc.setFont('helvetica', 'bold')
      doc.text('Chloride Exide (K) Ltd — Battery Finder Search Log', 14, 16)
      doc.setFontSize(9)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(100)
      doc.text(`Generated: ${dateStr} ${timeStr}   ·   Total records: ${res.total.toLocaleString()}`, 14, 23)
      doc.setTextColor(0)

      autoTable(doc, {
        startY: 28,
        head: [['#', 'Timestamp', 'Vehicle', 'Input Type', 'Battery Returned', 'Match Type', 'Conf %', 'Matched', 'IP Address']],
        body: res.items.map(r => {
          const vehicle = [r.make, r.model, r.year].filter(Boolean).join(' ')
          const specs = [r.engine_cc ? `${r.engine_cc} cc` : null, r.fuel_type].filter(Boolean).join(' · ')
          return [
            r.id,
            r.timestamp ? new Date(r.timestamp).toLocaleString('en-GB') : '—',
            [vehicle, specs].filter(Boolean).join(' — ') || '—',
            r.input_type ? (INPUT_TYPE_LABELS[r.input_type] ?? r.input_type) : '—',
            r.battery_returned ? `${r.battery_returned}${r.battery_ah ? ` · ${r.battery_ah} Ah` : ''}` : '—',
            r.match_type ?? '—',
            r.confidence !== null ? `${r.confidence}%` : '—',
            r.matched ? 'Yes' : 'No',
            r.ip_address ?? '—',
          ]
        }),
        styles: { fontSize: 7.5, cellPadding: 2 },
        headStyles: { fillColor: [0, 87, 148], textColor: 255, fontStyle: 'bold', fontSize: 7.5 },
        alternateRowStyles: { fillColor: [245, 248, 252] },
        columnStyles: { 0: { cellWidth: 12 }, 1: { cellWidth: 32 }, 4: { cellWidth: 28 }, 5: { cellWidth: 32 } },
      })

      doc.save(`search-log-${now.toISOString().slice(0, 10)}.pdf`)
    } finally {
      setPdfLoading(false)
    }
  }

  const load = useCallback(async (p: number) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchSearchEvents(p, PAGE_SIZE)
      setItems(res.items)
      setTotal(res.total)
    } catch {
      setError('Failed to load search events.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(page) }, [page, load])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <AdminLayout>
      <div style={{ padding: '2rem', maxWidth: 1400, margin: '0 auto' }}>

        {/* ── Page header ── */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.9rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <MagnifyingGlassIcon style={{ width: 24, height: 24, color: '#005794', flexShrink: 0 }} />
              <div>
                <h1 style={{ margin: 0, fontSize: '1.3rem', fontWeight: 800, color: 'var(--adm-text-1)', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
                  Search Log
                </h1>
                <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--adm-text-3)', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
                  {total.toLocaleString()} searches recorded in total
                </p>
              </div>
            </div>
            <button
              onClick={generatePdf}
              disabled={pdfLoading || total === 0}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.45rem',
                padding: '0.5rem 1rem', borderRadius: '8px',
                background: pdfLoading || total === 0 ? 'var(--adm-card-border)' : '#005794',
                color: pdfLoading || total === 0 ? 'var(--adm-text-3)' : '#fff',
                border: 'none', cursor: pdfLoading || total === 0 ? 'not-allowed' : 'pointer',
                fontSize: '0.78rem', fontWeight: 700,
                fontFamily: "'Segoe UI', system-ui, sans-serif",
                transition: 'background 0.15s',
              }}
            >
              <DocumentArrowDownIcon style={{ width: 16, height: 16 }} />
              {pdfLoading ? 'Generating…' : 'Download PDF'}
            </button>
          </div>

          {/* ── Info banner ── */}
          <div style={{
            display: 'flex', gap: '0.75rem', alignItems: 'flex-start',
            background: 'rgba(0,87,148,0.06)',
            border: '1px solid rgba(0,87,148,0.18)',
            borderRadius: '12px',
            padding: '0.9rem 1.1rem',
            fontFamily: "'Segoe UI', system-ui, sans-serif",
          }}>
            <InformationCircleIcon style={{ width: 18, height: 18, color: '#005794', flexShrink: 0, marginTop: '0.05rem' }} />
            <div>
              <p style={{ margin: '0 0 0.25rem', fontSize: '0.8rem', fontWeight: 700, color: '#005794' }}>
                What is this page?
              </p>
              <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--adm-text-2)', lineHeight: 1.6 }}>
                Every time a customer uses the Battery Finder tool to search for a battery, it gets
                recorded here automatically. Each row shows the vehicle searched, what battery was
                recommended, how confident the result was, and the IP address the search came from.
                No personal details are collected — only technical search information.
              </p>
            </div>
          </div>
        </div>

        {/* ── Table card ── */}
        <div style={CARD}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--adm-text-3)', fontSize: '0.85rem' }}>Loading…</div>
          ) : error ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: '#dc2626', fontSize: '0.85rem' }}>{error}</div>
          ) : items.length === 0 ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--adm-text-3)', fontSize: '0.85rem' }}>No searches recorded yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
                <thead>
                  <tr>
                    <th style={TH}>#</th>
                    <th style={TH}>Timestamp</th>
                    <th style={TH}>Vehicle</th>
                    <th style={TH}>Input Type</th>
                    <th style={TH}>Battery Returned</th>
                    <th style={TH}>Match Type</th>
                    <th style={TH}>Confidence</th>
                    <th style={TH}>Matched</th>
                    <th style={TH}>IP Address</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, i) => (
                    <tr
                      key={row.id}
                      style={{ borderBottom: '1px solid var(--adm-card-border)', background: i % 2 === 0 ? 'transparent' : 'var(--adm-table-stripe, rgba(0,0,0,0.015))' }}
                    >
                      {/* # */}
                      <td style={{ ...TD, color: 'var(--adm-text-3)', fontSize: '0.72rem' }}>{row.id}</td>

                      {/* Timestamp */}
                      <td style={{ ...TD, whiteSpace: 'nowrap', fontSize: '0.74rem' }}>{fmt(row.timestamp)}</td>

                      {/* Vehicle: make · model · year, plus cc/fuel if supplied */}
                      <td style={TD}>
                        {row.make || row.model || row.year ? (
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--adm-text-1)' }}>{row.make ?? '—'}</span>
                            {row.model && <span style={{ color: 'var(--adm-text-2)' }}> {row.model}</span>}
                            {row.year  && <span style={{ color: 'var(--adm-text-3)', fontSize: '0.72rem' }}> {row.year}</span>}
                            {(row.engine_cc || row.fuel_type) && (
                              <div style={{ color: 'var(--adm-text-3)', fontSize: '0.7rem', marginTop: '0.1rem', whiteSpace: 'nowrap' }}>
                                {row.engine_cc && <span>{row.engine_cc.toLocaleString()} cc</span>}
                                {row.engine_cc && row.fuel_type && <span> · </span>}
                                {row.fuel_type && <span style={{ textTransform: 'capitalize' }}>{row.fuel_type}</span>}
                              </div>
                            )}
                          </div>
                        ) : <Dash />}
                      </td>

                      {/* Input Type: typed vs selected */}
                      <td style={TD}><InputTypeBadge value={row.input_type} /></td>

                      {/* Battery Returned */}
                      <td style={{ ...TD, whiteSpace: 'nowrap' }}>
                        {row.battery_returned ? (
                          <span>
                            <span style={{ fontWeight: 600, color: 'var(--adm-text-1)', fontFamily: 'monospace', fontSize: '0.76rem' }}>{row.battery_returned}</span>
                            {row.battery_ah && <span style={{ color: 'var(--adm-text-3)', fontSize: '0.72rem' }}> · {row.battery_ah} Ah</span>}
                          </span>
                        ) : <Dash />}
                      </td>

                      {/* Match Type */}
                      <td style={TD}><MatchTypeBadge value={row.match_type} /></td>

                      {/* Confidence */}
                      <td style={TD}><ConfidenceBar value={row.confidence} /></td>

                      {/* Matched */}
                      <td style={TD}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.76rem', fontWeight: 700, color: row.matched ? '#15803d' : '#b45309' }}>
                          <span style={{ width: 7, height: 7, borderRadius: '50%', background: row.matched ? '#10b981' : '#f59e0b', display: 'inline-block', flexShrink: 0 }} />
                          {row.matched ? 'Yes' : 'No'}
                        </span>
                      </td>

                      {/* IP Address */}
                      <td style={{ ...TD, fontFamily: 'monospace', fontSize: '0.73rem' }}>
                        {row.ip_address ?? <Dash />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Pagination ── */}
          {!loading && total > PAGE_SIZE && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.75rem 1rem', borderTop: '1px solid var(--adm-card-border)' }}>
              <span style={{ fontSize: '0.75rem', color: 'var(--adm-text-3)', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
                Page {page} of {totalPages} · {total.toLocaleString()} events
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem', padding: '0.3rem 0.7rem', borderRadius: 6, border: '1px solid var(--adm-card-border)', background: 'transparent', cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.4 : 1, fontSize: '0.78rem', color: 'var(--adm-text-2)', fontFamily: "'Segoe UI', system-ui, sans-serif" }}
                >
                  <ChevronLeftIcon style={{ width: 13, height: 13 }} /> Prev
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem', padding: '0.3rem 0.7rem', borderRadius: 6, border: '1px solid var(--adm-card-border)', background: 'transparent', cursor: page === totalPages ? 'not-allowed' : 'pointer', opacity: page === totalPages ? 0.4 : 1, fontSize: '0.78rem', color: 'var(--adm-text-2)', fontFamily: "'Segoe UI', system-ui, sans-serif" }}
                >
                  Next <ChevronRightIcon style={{ width: 13, height: 13 }} />
                </button>
              </div>
            </div>
          )}
        </div>

      </div>
    </AdminLayout>
  )
}
