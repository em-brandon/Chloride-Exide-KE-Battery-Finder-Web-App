import { useState, useEffect, useRef, useCallback } from 'react'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  getWebValidateCoverage,
  getWebValidateMatched,
  getPipelineStaleness,
  type CoverageInfo,
  type MatchedVehicleRow,
} from '@/lib/adminApi'

// ── Types ─────────────────────────────────────────────────────────────────────

interface UnmatchedRow {
  make_n:    string
  model_n:   string
  year:      number
  engine_cc: number | null
  fuel_type: string | null
}

// ── AdminCoverage ─────────────────────────────────────────────────────────────

export default function AdminCoverage() {
  const [coverage,  setCoverage]  = useState<CoverageInfo | null>(null)
  const [staleness, setStaleness] = useState<{ stale: boolean; vehicles_last_updated_at: string | null; new_vehicles_since_last_run: number } | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')

  // Unmatched table state
  const [umSearch, setUmSearch] = useState('')
  const [umPage,   setUmPage]   = useState(1)
  const [umRows,   setUmRows]   = useState<UnmatchedRow[]>([])
  const [umTotal,  setUmTotal]  = useState(0)
  const umDebounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Matched panel state
  const [showMatched,  setShowMatched]  = useState(false)
  const [mSearch,      setMSearch]      = useState('')
  const [mPage,        setMPage]        = useState(1)
  const [mRows,        setMRows]        = useState<MatchedVehicleRow[]>([])
  const [mTotal,       setMTotal]       = useState(0)
  const [mLoading,     setMLoading]     = useState(false)

  const PAGE_SIZE = 50

  // Load coverage + staleness
  async function loadCoverage() {
    setLoading(true)
    setError('')
    try {
      const [cov, stale] = await Promise.all([
        getWebValidateCoverage(),
        getPipelineStaleness(),
      ])
      setCoverage(cov)
      setStaleness(stale)
      setUmRows(cov.unmatched_vehicles.slice(0, PAGE_SIZE))
      setUmTotal(cov.unmatched_vehicles.length)
    } catch {
      setError('Failed to load coverage data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadCoverage() }, [])

  // Unmatched client-side search + pagination
  const filteredUnmatched = useCallback((): UnmatchedRow[] => {
    if (!coverage) return []
    const q = umSearch.trim().toLowerCase()
    if (!q) return coverage.unmatched_vehicles
    return coverage.unmatched_vehicles.filter(r =>
      r.make_n.toLowerCase().includes(q) ||
      r.model_n.toLowerCase().includes(q) ||
      String(r.year).includes(q) ||
      (r.fuel_type ?? '').toLowerCase().includes(q)
    )
  }, [coverage, umSearch])

  useEffect(() => {
    if (umDebounce.current) clearTimeout(umDebounce.current)
    umDebounce.current = setTimeout(() => {
      const rows = filteredUnmatched()
      setUmTotal(rows.length)
      setUmPage(1)
      setUmRows(rows.slice(0, PAGE_SIZE))
    }, 300)
  }, [umSearch, coverage, filteredUnmatched])

  function umChangePage(p: number) {
    const rows = filteredUnmatched()
    setUmPage(p)
    setUmRows(rows.slice((p - 1) * PAGE_SIZE, p * PAGE_SIZE))
  }

  // Matched server-side pagination
  async function loadMatched(page = mPage, search = mSearch) {
    setMLoading(true)
    try {
      const r = await getWebValidateMatched(page, PAGE_SIZE, search)
      setMRows(r.items)
      setMTotal(r.total)
    } catch { /* ignore */ }
    finally { setMLoading(false) }
  }

  useEffect(() => {
    if (!showMatched) return
    const t = setTimeout(() => loadMatched(1, mSearch), 300)
    return () => clearTimeout(t)
  }, [mSearch, showMatched])

  async function toggleMatched() {
    const next = !showMatched
    setShowMatched(next)
    if (next && mRows.length === 0) loadMatched(1, '')
  }

  const pct      = coverage ? coverage.pct_matched : 0
  const pctColor = pct > 80 ? '#15803d' : pct > 50 ? '#d97706' : '#CC0000'

  return (
    <AdminLayout>
      <div style={{ padding: '1.5rem', maxWidth: 1200, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

        {/* Staleness banner */}
        {staleness?.stale && (
          <div style={{
            background: '#fef3c7', border: '1px solid #fde68a', borderRadius: 10,
            padding: '0.65rem 1rem', fontSize: '0.8rem', color: '#92400e', display: 'flex', gap: '0.5rem', alignItems: 'center',
          }}>
            <span>⚠</span>
            <span>
              {staleness.new_vehicles_since_last_run} new vehicle combos added since last pipeline run
              {staleness.vehicles_last_updated_at ? ` (last run ${new Date(staleness.vehicles_last_updated_at).toLocaleString()})` : ''}.
              {' '}Run the pipeline to update coverage.
            </span>
          </div>
        )}

        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h1 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--adm-text-1)' }}>Battery Coverage</h1>
          <button
            onClick={loadCoverage}
            disabled={loading}
            style={{
              background: '#fff5f5', color: '#CC0000', border: '1px solid #fecaca',
              borderRadius: 8, padding: '0.4rem 0.9rem', fontSize: '0.78rem', fontWeight: 700,
              cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Loading…' : '↻ Refresh'}
          </button>
        </div>

        {error && (
          <div style={{ background: '#fff5f5', border: '1px solid #fecaca', borderRadius: 8, padding: '0.65rem 1rem', color: '#CC0000', fontSize: '0.82rem' }}>
            {error}
          </div>
        )}

        {/* Hero row */}
        {coverage && (
          <div style={{
            background: 'var(--adm-card-bg)', border: '1px solid var(--adm-card-border)',
            borderRadius: 14, boxShadow: 'var(--adm-card-shadow)',
            padding: '1.5rem 2rem',
            display: 'flex', alignItems: 'center', gap: '2.5rem', flexWrap: 'wrap',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <DonutChart pct={pct} color={pctColor} />
              <div>
                <div style={{ fontSize: '3rem', fontWeight: 900, color: pctColor, lineHeight: 1 }}>
                  {pct.toFixed(1)}%
                </div>
                <div style={{ fontSize: '0.85rem', color: 'var(--adm-text-2)', marginTop: 4 }}>
                  of vehicles covered
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)', marginTop: 2 }}>
                  {coverage.matched.toLocaleString()} / {coverage.total.toLocaleString()} combos matched
                </div>
              </div>
            </div>

            {/* 4-column stat grid */}
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginLeft: 'auto' }}>
              {[
                { label: 'Committed to Master', value: coverage.master_count,       color: '#6366f1' },
                { label: 'In Staging',           value: coverage.staging_count,      color: '#f59e0b', hide: coverage.staging_count === 0 },
                { label: 'Buckets Remaining',    value: `${coverage.remaining_buckets} / ${coverage.total_buckets}`, color: '#0ea5e9' },
                { label: 'Web Cache Entries',    value: coverage.web_cache_size,     color: '#22c55e' },
              ].filter(s => !s.hide).map(s => (
                <div key={s.label} style={{
                  background: 'var(--adm-subtle-bg)', borderRadius: 12,
                  border: '1px solid var(--adm-card-border)',
                  padding: '0.85rem 1.25rem', minWidth: 140, textAlign: 'center',
                }}>
                  <div style={{ fontSize: '1.5rem', fontWeight: 800, color: s.color }}>{String(s.value)}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--adm-text-2)', marginTop: 4 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Unmatched vehicles table */}
        {coverage && (
          <div style={{
            background: 'var(--adm-card-bg)', border: '1px solid var(--adm-card-border)',
            borderRadius: 14, boxShadow: 'var(--adm-card-shadow)', overflow: 'hidden',
          }}>
            <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--adm-text-1)' }}>Unmatched Vehicles</span>
                <span style={{ background: '#fff5f5', color: '#CC0000', border: '1px solid #fecaca', fontSize: '0.7rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 20 }}>
                  {coverage.unmatched.toLocaleString()}
                </span>
              </div>
              <input
                value={umSearch}
                onChange={e => setUmSearch(e.target.value)}
                placeholder="Search make, model, year, fuel…"
                style={{
                  padding: '0.4rem 0.75rem', borderRadius: 8,
                  border: '1px solid var(--adm-input-border)',
                  background: 'var(--adm-input-bg)',
                  color: 'var(--adm-text-1)',
                  fontSize: '0.8rem', width: 260, outline: 'none',
                }}
              />
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ background: 'var(--adm-thead-bg)' }}>
                    {['Make', 'Model', 'Year', 'Engine CC', 'Fuel Type'].map(h => (
                      <th key={h} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'var(--adm-text-2)', borderBottom: '1px solid var(--adm-sep)', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {umRows.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>
                      {umSearch ? 'No matches found.' : 'All vehicles are matched!'}
                    </td></tr>
                  )}
                  {umRows.map((r, i) => (
                    <tr key={`${r.make_n}-${r.model_n}-${r.year}`} style={{
                      background: i % 2 === 0 ? 'transparent' : 'var(--adm-faint-bg)',
                      borderBottom: '1px solid var(--adm-row-border)',
                    }}>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.make_n}</td>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.model_n}</td>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.year}</td>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-2)' }}>{r.engine_cc ?? '–'}</td>
                      <td style={{ padding: '0.45rem 0.75rem' }}>
                        {r.fuel_type ? (
                          <span style={{ background: '#f0fdf4', color: '#15803d', padding: '0.1rem 0.4rem', borderRadius: 6, fontSize: '0.72rem', fontWeight: 600 }}>
                            {r.fuel_type}
                          </span>
                        ) : '–'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Pagination */}
            {umTotal > PAGE_SIZE && (
              <div style={{ padding: '0.75rem 1.25rem', borderTop: '1px solid var(--adm-sep)', display: 'flex', gap: '0.5rem', alignItems: 'center', justifyContent: 'flex-end' }}>
                <button disabled={umPage === 1} onClick={() => umChangePage(umPage - 1)} style={pagBtn(umPage === 1)}>← Prev</button>
                <span style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)' }}>
                  Page {umPage} / {Math.ceil(umTotal / PAGE_SIZE)}
                </span>
                <button disabled={umPage * PAGE_SIZE >= umTotal} onClick={() => umChangePage(umPage + 1)} style={pagBtn(umPage * PAGE_SIZE >= umTotal)}>Next →</button>
              </div>
            )}
          </div>
        )}

        {/* Matched vehicles (collapsible) */}
        {coverage && (
          <div style={{
            background: 'var(--adm-card-bg)', border: '1px solid var(--adm-card-border)',
            borderRadius: 14, boxShadow: 'var(--adm-card-shadow)', overflow: 'hidden',
          }}>
            <button
              onClick={toggleMatched}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: '0.75rem',
                padding: '1rem 1.25rem', background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: showMatched ? '1px solid var(--adm-sep)' : 'none',
                textAlign: 'left',
              }}
            >
              <span style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>
                {showMatched ? '▼' : '▶'} Matched Vehicles
              </span>
              <span style={{ background: '#dcfce7', color: '#15803d', fontSize: '0.7rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 20 }}>
                {coverage.matched.toLocaleString()}
              </span>
            </button>

            {showMatched && (
              <>
                <div style={{ padding: '0.75rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', justifyContent: 'flex-end' }}>
                  <input
                    value={mSearch}
                    onChange={e => { setMSearch(e.target.value); setMPage(1) }}
                    placeholder="Search matched vehicles…"
                    style={{
                      padding: '0.4rem 0.75rem', borderRadius: 8,
                      border: '1px solid var(--adm-input-border)',
                      background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)',
                      fontSize: '0.8rem', width: 260, outline: 'none',
                    }}
                  />
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ background: 'var(--adm-thead-bg)' }}>
                        {['Make', 'Model', 'Year', 'Battery', 'Ah', 'Tech', 'Source', 'Validated'].map(h => (
                          <th key={h} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'var(--adm-text-2)', borderBottom: '1px solid var(--adm-sep)', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {mLoading && (
                        <tr><td colSpan={8} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>Loading…</td></tr>
                      )}
                      {!mLoading && mRows.map((r, i) => (
                        <tr key={`${r.make_n}-${r.model_n}-${r.year}`} style={{
                          background: i % 2 === 0 ? 'transparent' : 'var(--adm-faint-bg)',
                          borderBottom: '1px solid var(--adm-row-border)',
                        }}>
                          <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.make_n}</td>
                          <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.model_n}</td>
                          <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }}>{r.year}</td>
                          <td style={{ padding: '0.45rem 0.75rem' }}>
                            {r.battery_code
                              ? <span style={{ background: '#fff5f5', color: '#CC0000', border: '1px solid #fecaca', padding: '0.15rem 0.5rem', borderRadius: 6, fontSize: '0.75rem', fontWeight: 800, fontFamily: 'monospace' }}>{r.battery_code}</span>
                              : <span style={{ color: 'var(--adm-text-2)' }}>–</span>}
                          </td>
                          <td style={{ padding: '0.45rem 0.75rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>{r.ah ?? '–'}</td>
                          <td style={{ padding: '0.45rem 0.75rem' }}>
                            {r.technology && (
                              <span style={{ background: '#e0e7ff', color: '#3730a3', padding: '0.1rem 0.4rem', borderRadius: 6, fontSize: '0.72rem', fontWeight: 700 }}>
                                {r.technology}
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-2)', fontSize: '0.72rem' }}>{r.source ?? '–'}</td>
                          <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-2)', fontSize: '0.72rem' }}>
                            {r.validated_at ? new Date(r.validated_at).toLocaleDateString() : '–'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {mTotal > PAGE_SIZE && (
                  <div style={{ padding: '0.75rem 1.25rem', borderTop: '1px solid var(--adm-sep)', display: 'flex', gap: '0.5rem', alignItems: 'center', justifyContent: 'flex-end' }}>
                    <button disabled={mPage === 1} onClick={() => { const p = mPage - 1; setMPage(p); loadMatched(p, mSearch) }} style={pagBtn(mPage === 1)}>← Prev</button>
                    <span style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)' }}>
                      Page {mPage} / {Math.ceil(mTotal / PAGE_SIZE)}
                    </span>
                    <button disabled={mPage * PAGE_SIZE >= mTotal} onClick={() => { const p = mPage + 1; setMPage(p); loadMatched(p, mSearch) }} style={pagBtn(mPage * PAGE_SIZE >= mTotal)}>Next →</button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </AdminLayout>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function DonutChart({ pct, color }: { pct: number; color: string }) {
  const r = 48, stroke = 13
  const circum = 2 * Math.PI * r
  const arc    = (pct / 100) * circum
  return (
    <svg width={116} height={116} viewBox="0 0 116 116">
      <circle cx={58} cy={58} r={r} fill="none" stroke="var(--adm-sep, #e2e4e9)" strokeWidth={stroke} />
      <circle cx={58} cy={58} r={r} fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeDasharray={`${arc} ${circum - arc}`}
        strokeLinecap="round"
        transform="rotate(-90 58 58)"
        style={{ transition: 'stroke-dasharray 0.6s ease' }}
      />
    </svg>
  )
}

function pagBtn(disabled: boolean): React.CSSProperties {
  return {
    background: 'var(--adm-subtle-bg)', border: '1px solid var(--adm-card-border)',
    borderRadius: 8, padding: '0.3rem 0.65rem', fontSize: '0.75rem',
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    color: 'var(--adm-text-1)', fontWeight: 600,
  }
}
