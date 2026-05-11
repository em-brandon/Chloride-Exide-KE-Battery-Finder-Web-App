import { useState, useEffect, useCallback } from 'react'
import {
  fetchFeedback,
  fetchFeedbackSummary,
  downloadFeedbackPdf,
  type FeedbackEntry,
  type FeedbackSummary,
} from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  ChatBubbleLeftRightIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  StarIcon,
  FunnelIcon,
  XMarkIcon,
  ArrowDownTrayIcon,
} from '@heroicons/react/20/solid'
import { StarIcon as StarOutline } from '@heroicons/react/24/outline'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R    = '#CC0000'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const ACCURACY_LABELS: Record<string, string> = {
  exact:  'Exact match',
  close:  'Close',
  wrong:  'Wrong',
  unsure: 'Unsure',
}
const ACCURACY_COLORS: Record<string, string> = {
  exact:  '#16a34a',
  close:  '#ca8a04',
  wrong:  '#dc2626',
  unsure: '#6b7280',
}

function AccuracyBadge({ value }: { value: string | null }) {
  if (!value) return <span style={{ color: '#9ca3af', fontSize: '0.78rem' }}>—</span>
  return (
    <span style={{
      display: 'inline-block',
      padding: '0.15rem 0.55rem',
      borderRadius: '999px',
      fontSize: '0.73rem',
      fontWeight: 700,
      background: `${ACCURACY_COLORS[value] ?? '#6b7280'}18`,
      color: ACCURACY_COLORS[value] ?? '#6b7280',
      border: `1px solid ${ACCURACY_COLORS[value] ?? '#6b7280'}44`,
    }}>
      {ACCURACY_LABELS[value] ?? value}
    </span>
  )
}

function StarDisplay({ value }: { value: number }) {
  return (
    <span style={{ display: 'inline-flex', gap: '2px', alignItems: 'center' }}>
      {[1,2,3,4,5].map(n => (
        n <= value
          ? <StarIcon key={n} style={{ width: '0.85rem', height: '0.85rem', color: '#f59e0b' }} />
          : <StarOutline key={n} style={{ width: '0.85rem', height: '0.85rem', color: '#d1d5db' }} />
      ))}
    </span>
  )
}

function WrongPartsChips({ parts }: { parts: Record<string, boolean> | null }) {
  if (!parts) return null
  const active = Object.entries(parts).filter(([, v]) => v).map(([k]) =>
    k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  )
  if (active.length === 0) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
      {active.map(label => (
        <span key={label} style={{
          padding: '0.1rem 0.4rem',
          borderRadius: '6px',
          background: '#fee2e2',
          color: '#991b1b',
          fontSize: '0.7rem',
          fontWeight: 600,
        }}>{label}</span>
      ))}
    </div>
  )
}

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
  return new Date(iso).toLocaleDateString()
}

// ── Summary strip ─────────────────────────────────────────────────────────────

function SummaryStrip({ summary }: { summary: FeedbackSummary | null }) {
  if (!summary) return null
  const stars = [1,2,3,4,5]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
      {/* Total */}
      <div style={{ ...CARD, padding: '1rem 1.25rem', borderTop: `3px solid ${R}` }}>
        <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#9ca3af', marginBottom: '0.4rem' }}>TOTAL RESPONSES</div>
        <div style={{ fontSize: '2.4rem', fontWeight: 900, color: R, lineHeight: 1 }}>{summary.total.toLocaleString()}</div>
      </div>

      {/* Avg satisfaction */}
      <div style={{ ...CARD, padding: '1rem 1.25rem', borderTop: '3px solid #f59e0b' }}>
        <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#9ca3af', marginBottom: '0.4rem' }}>AVG SATISFACTION</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '2.4rem', fontWeight: 900, color: '#f59e0b', lineHeight: 1 }}>
            {summary.avg_satisfaction != null ? summary.avg_satisfaction.toFixed(1) : '—'}
          </span>
          <StarIcon style={{ width: '1.5rem', height: '1.5rem', color: '#f59e0b' }} />
        </div>
        {/* Star breakdown mini-bar */}
        <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '3px' }}>
          {stars.slice().reverse().map(s => {
            const count = summary.star_breakdown[String(s)] ?? 0
            const pct = summary.total > 0 ? (count / summary.total) * 100 : 0
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ fontSize: '0.65rem', color: '#9ca3af', width: '10px', textAlign: 'right' }}>{s}</span>
                <div style={{ flex: 1, height: '5px', background: '#f3f4f6', borderRadius: '99px', overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: '#f59e0b', transition: 'width 0.5s ease', borderRadius: '99px' }} />
                </div>
                <span style={{ fontSize: '0.65rem', color: '#9ca3af', width: '22px' }}>{count}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Accuracy breakdown */}
      <div style={{ ...CARD, padding: '1rem 1.25rem', borderTop: '3px solid #6366f1', gridColumn: 'span 2' }}>
        <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#9ca3af', marginBottom: '0.75rem' }}>ACCURACY BREAKDOWN</div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          {(['exact','close','wrong','unsure','not_given'] as const).map(key => {
            const count = summary.accuracy_breakdown[key] ?? 0
            const pct = summary.total > 0 ? Math.round((count / summary.total) * 100) : 0
            const color = ACCURACY_COLORS[key] ?? '#6b7280'
            return (
              <div key={key} style={{ textAlign: 'center', minWidth: '64px' }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 900, color }}>{count}</div>
                <div style={{ fontSize: '0.65rem', color: '#9ca3af', marginBottom: '2px' }}>{ACCURACY_LABELS[key] ?? 'Not given'}</div>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color }}>{pct}%</div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminFeedback() {
  const [items, setItems]         = useState<FeedbackEntry[]>([])
  const [total, setTotal]          = useState(0)
  const [page, setPage]            = useState(1)
  const [accuracy, setAccuracy]    = useState('')
  const [summary, setSummary]      = useState<FeedbackSummary | null>(null)
  const [loading, setLoading]      = useState(true)
  const [error, setError]          = useState('')
  const [exporting, setExporting]  = useState(false)

  const PAGE_SIZE = 25

  const load = useCallback(async (p: number, acc: string) => {
    setLoading(true)
    setError('')
    try {
      const [res, sumRes] = await Promise.all([
        fetchFeedback(p, PAGE_SIZE, acc || undefined),
        p === 1 ? fetchFeedbackSummary() : Promise.resolve(null),
      ])
      setItems(res.items)
      setTotal(res.total)
      if (sumRes) setSummary(sumRes)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load feedback')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(page, accuracy) }, [load, page, accuracy])

  function handleAccuracyFilter(val: string) {
    setAccuracy(val)
    setPage(1)
  }

  async function handleExportPdf() {
    setExporting(true)
    try {
      await downloadFeedbackPdf(accuracy || undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PDF export failed')
    } finally {
      setExporting(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <AdminLayout>
      <div style={{ padding: '2rem', fontFamily: "'Segoe UI', system-ui, sans-serif", maxWidth: '1200px' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <ChatBubbleLeftRightIcon style={{ width: '1.5rem', height: '1.5rem', color: R }} />
            <div>
              <h1 style={{ fontSize: '1.35rem', fontWeight: 800, color: '#111827', margin: 0 }}>Feedback Report</h1>
              <p style={{ fontSize: '0.78rem', color: '#6b7280', margin: 0 }}>User-submitted results from the battery finder</p>
            </div>
          </div>

          {/* Filter */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FunnelIcon style={{ width: '1rem', height: '1rem', color: '#9ca3af' }} />
            <select
              value={accuracy}
              onChange={e => handleAccuracyFilter(e.target.value)}
              style={{ borderRadius: '8px', border: '1px solid #d1d5db', background: '#fff', padding: '0.35rem 0.7rem', fontSize: '0.82rem', fontFamily: 'inherit', cursor: 'pointer' }}
            >
              <option value="">All accuracy</option>
              <option value="exact">Exact match</option>
              <option value="close">Close</option>
              <option value="wrong">Wrong</option>
              <option value="unsure">Unsure</option>
            </select>
            {accuracy && (
              <button
                onClick={() => handleAccuracyFilter('')}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: '4px' }}
                aria-label="Clear filter"
              >
                <XMarkIcon style={{ width: '1rem', height: '1rem' }} />
              </button>
            )}

            {/* Export PDF */}
            <button
              onClick={handleExportPdf}
              disabled={exporting || total === 0}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.4rem 0.85rem',
                borderRadius: '8px',
                border: `1px solid ${R}`,
                background: exporting || total === 0 ? '#f9fafb' : R,
                color: exporting || total === 0 ? '#9ca3af' : '#fff',
                cursor: exporting || total === 0 ? 'default' : 'pointer',
                fontSize: '0.82rem',
                fontWeight: 600,
                fontFamily: 'inherit',
                transition: 'opacity 0.15s',
              }}
              title={accuracy ? `Export filtered (${accuracy}) as PDF` : 'Export all feedback as PDF'}
            >
              <ArrowDownTrayIcon style={{ width: '0.9rem', height: '0.9rem' }} />
              {exporting ? 'Exporting…' : 'Export PDF'}
            </button>
          </div>
        </div>

        {/* Summary stats */}
        {!accuracy && <SummaryStrip summary={summary} />}

        {/* Error */}
        {error && (
          <div style={{ ...CARD, padding: '1rem 1.25rem', color: R, marginBottom: '1rem' }}>{error}</div>
        )}

        {/* Table card */}
        <div style={{ ...CARD, overflow: 'hidden' }}>
          {/* Table header */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #e2e4e9', background: '#f9fafb' }}>
                  {['User', 'Vehicle', 'Input', 'Rating', 'Confidence', 'Match Type', 'Accuracy', 'Wrong parts flagged', 'Comments', 'Submitted'].map(h => (
                    <th key={h} style={{ padding: '0.7rem 1rem', textAlign: 'left', fontWeight: 700, fontSize: '0.68rem', letterSpacing: '0.08em', textTransform: 'uppercase', color: '#6b7280', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={10} style={{ padding: '3rem', textAlign: 'center', color: '#9ca3af' }}>Loading…</td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={10} style={{ padding: '3rem', textAlign: 'center', color: '#9ca3af' }}>No feedback entries found.</td></tr>
                )}
                {!loading && items.map((row, i) => (
                  <tr key={row.id} style={{ borderBottom: '1px solid #f3f4f6', background: i % 2 === 0 ? '#fff' : '#fafafa' }}>
                    <td style={{ padding: '0.7rem 1rem', whiteSpace: 'nowrap' }}>
                      {row.test_username
                        ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem', padding: '0.15rem 0.55rem', borderRadius: '999px', background: '#f0fdf4', color: '#16a34a', border: '1px solid #bbf7d0', fontSize: '0.75rem', fontWeight: 700 }}>
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" style={{ width: '0.75rem', height: '0.75rem' }}><path d="M10 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM3.465 14.493a1.23 1.23 0 0 0 .41 1.412A9.957 9.957 0 0 0 10 18c2.31 0 4.438-.784 6.131-2.1.43-.333.604-.903.408-1.41a7.002 7.002 0 0 0-13.074.003Z" /></svg>
                            {row.test_username}
                          </span>
                        : <span style={{ color: '#d1d5db', fontSize: '0.75rem' }}>anonymous</span>
                      }
                    </td>
                    <td style={{ padding: '0.7rem 1rem', fontWeight: 600, color: '#111827', maxWidth: '200px' }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.vehicle_label}>
                        {row.vehicle_label}
                      </div>
                    </td>
                    <td style={{ padding: '0.7rem 1rem', whiteSpace: 'nowrap' }}>
                      {row.input_type
                        ? <span style={{
                            display: 'inline-block', padding: '0.12rem 0.5rem', borderRadius: '999px',
                            fontSize: '0.7rem', fontWeight: 700,
                            background: row.input_type === 'type' ? '#eff6ff' : '#f5f3ff',
                            color: row.input_type === 'type' ? '#1d4ed8' : '#7c3aed',
                            border: `1px solid ${row.input_type === 'type' ? '#bfdbfe' : '#ddd6fe'}`,
                          }}>{row.input_type === 'type' ? 'Typed' : 'Select'}</span>
                        : <span style={{ color: '#d1d5db', fontSize: '0.75rem' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '0.7rem 1rem', whiteSpace: 'nowrap' }}>
                      <StarDisplay value={row.satisfaction} />
                    </td>
                    <td style={{ padding: '0.7rem 1rem', whiteSpace: 'nowrap' }}>
                      {row.match_confidence != null
                        ? <span style={{
                            display: 'inline-block', padding: '0.12rem 0.5rem', borderRadius: '999px',
                            fontSize: '0.7rem', fontWeight: 700,
                            background: row.match_confidence >= 80 ? '#f0fdf4' : row.match_confidence >= 50 ? '#fffbeb' : '#fff1f2',
                            color: row.match_confidence >= 80 ? '#16a34a' : row.match_confidence >= 50 ? '#ca8a04' : '#dc2626',
                            border: `1px solid ${row.match_confidence >= 80 ? '#bbf7d0' : row.match_confidence >= 50 ? '#fde68a' : '#fecdd3'}`,
                          }}>{row.match_confidence}%</span>
                        : <span style={{ color: '#d1d5db', fontSize: '0.75rem' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '0.7rem 1rem', whiteSpace: 'nowrap' }}>
                      {row.match_type
                        ? <span style={{
                            display: 'inline-block', padding: '0.12rem 0.5rem', borderRadius: '999px',
                            fontSize: '0.7rem', fontWeight: 600,
                            background: '#f9fafb',
                            color: '#374151',
                            border: '1px solid #e2e4e9',
                          }}>{row.match_type.replace(/_/g, ' ')}</span>
                        : <span style={{ color: '#d1d5db', fontSize: '0.75rem' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '0.7rem 1rem' }}>
                      <AccuracyBadge value={row.accuracy} />
                    </td>
                    <td style={{ padding: '0.7rem 1rem' }}>
                      <WrongPartsChips parts={row.wrong_parts} />
                    </td>
                    <td style={{ padding: '0.7rem 1rem', color: '#374151', maxWidth: '260px' }}>
                      {row.comments
                        ? <span title={row.comments} style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{row.comments}</span>
                        : <span style={{ color: '#d1d5db' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '0.7rem 1rem', color: '#9ca3af', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                      <span title={new Date(row.submitted_at).toLocaleString()}>{relativeTime(row.submitted_at)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.75rem 1rem', borderTop: '1px solid #e2e4e9', background: '#f9fafb' }}>
              <span style={{ fontSize: '0.78rem', color: '#6b7280' }}>
                {total} response{total !== 1 ? 's' : ''} — page {page} of {totalPages}
              </span>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{ padding: '0.3rem 0.6rem', borderRadius: '6px', border: '1px solid #e2e4e9', background: page === 1 ? '#f9fafb' : '#fff', cursor: page === 1 ? 'default' : 'pointer', color: page === 1 ? '#d1d5db' : '#374151' }}
                >
                  <ChevronLeftIcon style={{ width: '1rem', height: '1rem' }} />
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  style={{ padding: '0.3rem 0.6rem', borderRadius: '6px', border: '1px solid #e2e4e9', background: page === totalPages ? '#f9fafb' : '#fff', cursor: page === totalPages ? 'default' : 'pointer', color: page === totalPages ? '#d1d5db' : '#374151' }}
                >
                  <ChevronRightIcon style={{ width: '1rem', height: '1rem' }} />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </AdminLayout>
  )
}
