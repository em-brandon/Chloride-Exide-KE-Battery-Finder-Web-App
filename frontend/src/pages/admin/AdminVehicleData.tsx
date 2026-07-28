import { useState, useEffect, useRef, useCallback } from 'react'
import AdminLayout from '@/components/admin/AdminLayout'
import { OrbitLoader } from '@/components/ui/OrbitLoader'
import { MAKE_LOGO, makeColor } from '@/lib/makeBranding'
import { TruckIcon, Squares2X2Icon, MagnifyingGlassIcon } from '@heroicons/react/20/solid'
import {
  getWebValidateCoverage,
  getWebValidateMatched,
  getPipelineStaleness,
  getVehicleDataOemFitment,
  getVehicleDataOemFitmentByMake,
  type CoverageInfo,
  type MatchedVehicleRow,
  type OemFitmentRow,
  type OemFitmentMakeStat,
} from '@/lib/adminApi'

const PAGE_SIZE = 50

type Tab = 'coverage' | 'fitment'

interface UnmatchedRow {
  make_n:    string
  model_n:   string
  year:      number
  engine_cc: number | null
  fuel_type: string | null
}

// ── AdminVehicleData ─────────────────────────────────────────────────────────
// Combines the two vehicle-data sources that feed the matcher's search
// dropdowns into one page: "Core Dataset Coverage" (vehicle_years, sourced
// from fueleconomy/NHTSA/CarAPI/Wikipedia/Wikidata, reported here against
// web-validation status) and "OEM Fitment" (oem_fitment, Exide's own global
// fitment guide — see pipelines/exide_fitment_clean.py). Kept as two tabs
// rather than one merged table since each source's shape and the questions
// admins ask of it are different: the core dataset's central question is
// "is this vehicle's battery web-validated yet", the fitment guide's is
// "what does Exide say this vehicle takes".

export default function AdminVehicleData() {
  const [tab, setTab] = useState<Tab>('coverage')
  const [coverageTotal, setCoverageTotal] = useState<number | null>(null)
  const [fitmentTotal,  setFitmentTotal]  = useState<number | null>(null)

  return (
    <AdminLayout>
      <div style={{ padding: '1.5rem', maxWidth: 1200, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h1 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--adm-text-1)' }}>Vehicle Data</h1>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '0.6rem' }}>
          <TabButton
            active={tab === 'coverage'} onClick={() => setTab('coverage')}
            label="Core Dataset Coverage" Icon={TruckIcon} count={coverageTotal ?? undefined}
          />
          <TabButton
            active={tab === 'fitment'} onClick={() => setTab('fitment')}
            label="OEM Fitment" Icon={Squares2X2Icon} count={fitmentTotal ?? undefined}
          />
        </div>

        {tab === 'coverage' && <CoverageTab onTotal={setCoverageTotal} />}
        {tab === 'fitment'  && <FitmentTab onTotal={setFitmentTotal} />}
      </div>
    </AdminLayout>
  )
}

// ── Core Dataset Coverage tab (formerly AdminCoverage.tsx) ──────────────────

function CoverageTab({ onTotal }: { onTotal?: (total: number) => void }) {
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
      onTotal?.(cov.total)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mSearch, showMatched])

  async function toggleMatched() {
    const next = !showMatched
    setShowMatched(next)
    if (next && mRows.length === 0) loadMatched(1, '')
  }

  const pct      = coverage ? coverage.pct_matched : 0
  const pctColor = pct > 80 ? '#15803d' : pct > 50 ? '#d97706' : '#CC0000'

  // Coverage-by-make table state
  const [makeSearch, setMakeSearch] = useState('')
  const [makeSortBy, setMakeSortBy] = useState<'make' | 'total' | 'pct'>('pct')
  const [makeSortAsc, setMakeSortAsc] = useState(true)

  function toggleMakeSort(col: 'make' | 'total' | 'pct') {
    if (makeSortBy === col) {
      setMakeSortAsc(a => !a)
    } else {
      setMakeSortBy(col)
      setMakeSortAsc(col === 'make')
    }
  }

  const byMakeRows = (coverage?.by_make ?? [])
    .filter(m => m.make.toLowerCase().includes(makeSearch.trim().toLowerCase()))
    .slice()
    .sort((a, b) => {
      const dir = makeSortAsc ? 1 : -1
      if (makeSortBy === 'make')  return a.make.localeCompare(b.make) * dir
      if (makeSortBy === 'total') return (a.total - b.total) * dir
      return (a.pct_matched - b.pct_matched) * dir
    })

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '3rem 0' }}>
        <OrbitLoader gradientId="ce-ringD" />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

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

      {/* Refresh row */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
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
              { label: 'Published to Master', value: coverage.master_count,       color: '#6366f1' },
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

      {/* Coverage by Make */}
      {coverage && (
        <div style={{
          background: 'var(--adm-card-bg)', border: '1px solid var(--adm-card-border)',
          borderRadius: 14, boxShadow: 'var(--adm-card-shadow)', overflow: 'hidden',
        }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
            <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--adm-text-1)' }}>Coverage by Make</span>
            <input
              value={makeSearch}
              onChange={e => setMakeSearch(e.target.value)}
              placeholder="Search make…"
              style={{
                padding: '0.4rem 0.75rem', borderRadius: 8,
                border: '1px solid var(--adm-input-border)',
                background: 'var(--adm-input-bg)',
                color: 'var(--adm-text-1)',
                fontSize: '0.8rem', width: 200, outline: 'none',
              }}
            />
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {([
                    ['make', 'Make'], ['total', 'Total Combos'], ['pct', 'Coverage'],
                  ] as const).map(([col, label]) => (
                    <th
                      key={col}
                      onClick={() => toggleMakeSort(col)}
                      style={{
                        padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700,
                        color: 'var(--adm-text-2)', borderBottom: '1px solid var(--adm-sep)',
                        whiteSpace: 'nowrap', cursor: 'pointer', userSelect: 'none',
                      }}
                    >
                      {label}{makeSortBy === col ? (makeSortAsc ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {byMakeRows.length === 0 && (
                  <tr><td colSpan={3} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>
                    {makeSearch ? 'No matches found.' : 'No coverage data yet.'}
                  </td></tr>
                )}
                {byMakeRows.map((m, i) => {
                  const color = m.pct_matched > 80 ? '#15803d' : m.pct_matched > 50 ? '#d97706' : '#CC0000'
                  return (
                    <tr key={m.make} style={{
                      background: i % 2 === 0 ? 'transparent' : 'var(--adm-faint-bg)',
                      borderBottom: '1px solid var(--adm-row-border)',
                    }}>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)', fontWeight: 600 }}>{m.make}</td>
                      <td style={{ padding: '0.45rem 0.75rem', color: 'var(--adm-text-2)' }}>
                        {m.matched.toLocaleString()} / {m.total.toLocaleString()}
                      </td>
                      <td style={{ padding: '0.45rem 0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <div style={{ width: 80, background: 'var(--adm-subtle-bg)', borderRadius: 99, height: 6, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.min(m.pct_matched, 100)}%`, background: color, height: '100%', borderRadius: 99 }} />
                          </div>
                          <span style={{ fontSize: '0.75rem', fontWeight: 700, color, minWidth: 40 }}>{m.pct_matched.toFixed(1)}%</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
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
  )
}

// ── OEM Fitment tab ───────────────────────────────────────────────────────────
// Brand-first browsing: a grid of make tiles (logo/monogram + stats) that
// expands in place to a per-make drill-down table on click — rather than one
// flat table mixing all 76 makes' rows together.

function FitmentTab({ onTotal }: { onTotal?: (total: number) => void }) {
  const [makes,        setMakes]        = useState<OemFitmentMakeStat[]>([])
  const [makesLoading, setMakesLoading] = useState(true)
  const [gridSearch,   setGridSearch]   = useState('')
  const [expandedMake, setExpandedMake] = useState<string | null>(null)

  const [fitSearch,  setFitSearch]  = useState('')
  const [fitPage,    setFitPage]    = useState(1)
  const [fitRows,    setFitRows]    = useState<OemFitmentRow[]>([])
  const [fitTotal,   setFitTotal]   = useState(0)
  const [fitLoading, setFitLoading] = useState(false)

  useEffect(() => {
    (async () => {
      setMakesLoading(true)
      try {
        const r = await getVehicleDataOemFitmentByMake()
        setMakes(r.makes)
        onTotal?.(r.makes.reduce((sum, m) => sum + m.row_count, 0))
      } catch { /* ignore */ }
      finally { setMakesLoading(false) }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadFitment(make: string, page: number, search: string) {
    setFitLoading(true)
    try {
      const r = await getVehicleDataOemFitment(page, PAGE_SIZE, search, make)
      setFitRows(r.items)
      setFitTotal(r.total)
    } catch { /* ignore */ }
    finally { setFitLoading(false) }
  }

  function toggleMake(make: string) {
    if (expandedMake === make) {
      setExpandedMake(null)
      return
    }
    setExpandedMake(make)
    setFitSearch('')
    setFitPage(1)
    loadFitment(make, 1, '')
  }

  useEffect(() => {
    if (!expandedMake) return
    const t = setTimeout(() => { setFitPage(1); loadFitment(expandedMake, 1, fitSearch) }, 300)
    return () => clearTimeout(t)
  }, [fitSearch, expandedMake])

  const visibleMakes = makes.filter(m =>
    m.make.toLowerCase().includes(gridSearch.trim().toLowerCase())
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ ...CARD, overflow: 'hidden' }}>
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--adm-text-1)' }}>Browse by Make</span>
            <span style={{ background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-2)', fontSize: '0.7rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 20 }}>
              {makes.length} makes
            </span>
          </div>
          <div style={{ position: 'relative' }}>
            <MagnifyingGlassIcon style={{ width: 13, height: 13, color: 'var(--adm-text-3)', position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }} />
            <input
              value={gridSearch}
              onChange={e => setGridSearch(e.target.value)}
              placeholder="Filter makes…"
              style={{
                padding: '0.4rem 0.75rem 0.4rem 1.9rem', borderRadius: 8,
                border: '1px solid var(--adm-input-border)',
                background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)',
                fontSize: '0.8rem', width: 220, outline: 'none',
              }}
            />
          </div>
        </div>

        <div style={{ padding: '1.25rem', display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
          {makesLoading && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem 0' }}>
              <OrbitLoader gradientId="ce-ringF" />
            </div>
          )}
          {!makesLoading && visibleMakes.length === 0 && (
            <div style={{ flex: 1, padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>
              {gridSearch ? 'No matching makes.' : 'No OEM fitment data yet.'}
            </div>
          )}
          {!makesLoading && visibleMakes.map((m, i) => (
            <MakeTile
              key={m.make}
              stat={m}
              active={expandedMake === m.make}
              onClick={() => toggleMake(m.make)}
              animDelay={Math.min(i * 12, 300)}
            />
          ))}
        </div>
      </div>

      {expandedMake && (
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
              <MakeBadge make={expandedMake} size={28} />
              <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--adm-text-1)' }}>{expandedMake}</span>
              <span style={{ background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-2)', fontSize: '0.7rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 20 }}>
                {fitTotal.toLocaleString()} rows
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                value={fitSearch}
                onChange={e => setFitSearch(e.target.value)}
                placeholder="Search model…"
                style={{
                  padding: '0.4rem 0.75rem', borderRadius: 8,
                  border: '1px solid var(--adm-input-border)',
                  background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)',
                  fontSize: '0.8rem', width: 220, outline: 'none',
                }}
              />
              <button onClick={() => setExpandedMake(null)} style={pagBtn(false)}>Close ✕</button>
            </div>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {['Model', 'Years', 'Ah', 'Technology', 'Dimensions', 'Cylinder CC'].map(h => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!fitLoading && fitRows.length === 0 && (
                  <tr><td colSpan={6} style={emptyStyle}>{fitSearch ? 'No matches found.' : 'No rows.'}</td></tr>
                )}
                {!fitLoading && fitRows.map(r => (
                  <tr key={r.id} style={rowStyle(r.id)}>
                    <td style={tdStyle}>{r.model}</td>
                    <td style={tdStyle}>{r.year_from}–{r.year_to ?? 'Present'}</td>
                    <td style={{ ...tdStyle, fontWeight: 700 }}>{r.ah ?? '–'}</td>
                    <td style={tdStyle}>
                      {r.technology && (
                        <span style={{ background: '#e0e7ff', color: '#3730a3', padding: '0.1rem 0.4rem', borderRadius: 6, fontSize: '0.72rem', fontWeight: 700 }}>
                          {r.technology}
                        </span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, color: 'var(--adm-text-2)', fontSize: '0.72rem' }}>{r.dimensions ?? '–'}</td>
                    <td style={{ ...tdStyle, color: 'var(--adm-text-2)', fontSize: '0.72rem' }}>{r.cylinder_capacity_cc ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {fitLoading && (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>Loading…</div>
            )}
          </div>
          {fitTotal > PAGE_SIZE && (
            <div style={{ padding: '0.75rem 1.25rem', borderTop: '1px solid var(--adm-sep)', display: 'flex', gap: '0.5rem', alignItems: 'center', justifyContent: 'flex-end' }}>
              <button disabled={fitPage === 1} onClick={() => { const p = fitPage - 1; setFitPage(p); loadFitment(expandedMake, p, fitSearch) }} style={pagBtn(fitPage === 1)}>← Prev</button>
              <span style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)' }}>
                Page {fitPage} / {Math.ceil(fitTotal / PAGE_SIZE)}
              </span>
              <button disabled={fitPage * PAGE_SIZE >= fitTotal} onClick={() => { const p = fitPage + 1; setFitPage(p); loadFitment(expandedMake, p, fitSearch) }} style={pagBtn(fitPage * PAGE_SIZE >= fitTotal)}>Next →</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function monogram(make: string): string {
  const words = make.trim().split(/\s+/)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return make.replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase()
}

function MakeBadge({ make, size = 40 }: { make: string; size?: number }) {
  const logo = MAKE_LOGO[make]
  const color = makeColor(make)

  if (logo) {
    return (
      <div style={{
        width: size, height: size, borderRadius: '50%',
        background: '#fff', border: `1px solid ${color}33`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'hidden', flexShrink: 0,
      }}>
        <img
          src={logo}
          alt={make}
          style={{ width: '78%', height: '78%', objectFit: 'contain' }}
        />
      </div>
    )
  }

  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: color, color: '#fff',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontWeight: 800, fontSize: size * 0.36, flexShrink: 0,
      fontFamily: "'Segoe UI', system-ui, sans-serif",
    }}>
      {monogram(make)}
    </div>
  )
}

function MakeTile({ stat, active, onClick, animDelay = 0 }: {
  stat: OemFitmentMakeStat
  active: boolean
  onClick: () => void
  animDelay?: number
}) {
  const color = makeColor(stat.make)
  const yearRange = stat.year_min && stat.year_max ? `${stat.year_min}–${stat.year_max}` : '–'
  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--adm-card-bg)',
        border: '1px solid var(--adm-card-border)',
        borderRadius: 12,
        padding: '1.1rem 1.1rem 0.9rem',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '0.6rem',
        width: 150,
        flex: '0 0 150px',
        transition: 'box-shadow 0.15s, transform 0.1s',
        cursor: 'pointer',
        borderTop: `3px solid ${color}`,
        boxShadow: active ? `0 0 0 2px ${color}55, var(--adm-card-shadow)` : 'var(--adm-card-shadow)',
        animationName: 'admCardIn', animationDuration: '0.4s',
        animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)', animationFillMode: 'both',
        animationDelay: `${animDelay}ms`,
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.transform = 'translateY(-2px)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'none' }}
    >
      <MakeBadge make={stat.make} size={44} />
      <span style={{
        fontSize: '0.78rem', fontWeight: 700, color: 'var(--adm-text-1)',
        textAlign: 'center', lineHeight: 1.2,
      }}>
        {stat.make}
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.72rem', color: 'var(--adm-text-2)' }}>
          {stat.model_count.toLocaleString()} {stat.model_count === 1 ? 'model' : 'models'}
        </span>
        <span style={{ fontSize: '0.68rem', color: 'var(--adm-text-3)' }}>{yearRange}</span>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function TabButton({ active, onClick, label, Icon, count }: {
  active: boolean
  onClick: () => void
  label: string
  Icon: React.ComponentType<{ style?: React.CSSProperties }>
  count?: number
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.55rem 1.1rem', cursor: 'pointer',
        borderRadius: 10,
        border: `1px solid ${active ? '#fecaca' : 'var(--adm-card-border)'}`,
        background: active ? '#fff5f5' : 'var(--adm-card-bg)',
        boxShadow: active ? 'none' : 'var(--adm-card-shadow)',
        fontSize: '0.83rem', fontWeight: 700,
        color: active ? '#CC0000' : 'var(--adm-text-2)',
        transition: 'all 0.15s',
      }}
    >
      <Icon style={{ width: 15, height: 15 }} />
      {label}
      {count !== undefined && (
        <span style={{
          background: active ? '#CC0000' : 'var(--adm-subtle-bg)',
          color: active ? '#fff' : 'var(--adm-text-2)',
          fontSize: '0.68rem', fontWeight: 800, padding: '0.1rem 0.5rem', borderRadius: 20,
          minWidth: 20, textAlign: 'center',
        }}>
          {count.toLocaleString()}
        </span>
      )}
    </button>
  )
}

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

const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  border: '1px solid var(--adm-card-border)',
  borderRadius: 12,
}

const thStyle: React.CSSProperties = {
  padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700,
  color: 'var(--adm-text-2)', borderBottom: '1px solid var(--adm-sep)', whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = { padding: '0.45rem 0.75rem', color: 'var(--adm-text-1)' }

const emptyStyle: React.CSSProperties = { padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }

function rowStyle(i: number): React.CSSProperties {
  return {
    background: i % 2 === 0 ? 'transparent' : 'var(--adm-faint-bg)',
    borderBottom: '1px solid var(--adm-row-border)',
  }
}

function pagBtn(disabled: boolean): React.CSSProperties {
  return {
    background: 'var(--adm-subtle-bg)', border: '1px solid var(--adm-card-border)',
    borderRadius: 8, padding: '0.3rem 0.65rem', fontSize: '0.75rem',
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    color: 'var(--adm-text-1)', fontWeight: 600,
  }
}
