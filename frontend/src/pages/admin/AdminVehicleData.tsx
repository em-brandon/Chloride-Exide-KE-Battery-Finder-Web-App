import { useState, useEffect } from 'react'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  getVehicleDataCore,
  getVehicleDataOemFitment,
  type CoreVehicleRow,
  type OemFitmentRow,
} from '@/lib/adminApi'

const PAGE_SIZE = 50

type Tab = 'core' | 'fitment'

// ── AdminVehicleData ─────────────────────────────────────────────────────────
// Read-only browser separating the two vehicle-data sources that feed the
// matcher's search dropdowns: the "Core Dataset" (vehicle_years, sourced from
// fueleconomy/NHTSA/CarAPI/Wikipedia/Wikidata) and "OEM Fitment" (oem_fitment,
// Exide's own global fitment guide — see pipelines/exide_fitment_clean.py).
// Kept as two separate tabs rather than one merged table so each source's
// distinct shape (core: single year + fuel; fitment: year range + Ah/tech)
// can be shown with its own natural columns instead of a lossy common subset.

export default function AdminVehicleData() {
  const [tab, setTab] = useState<Tab>('core')

  // Core Dataset tab state
  const [coreSearch,  setCoreSearch]  = useState('')
  const [corePage,    setCorePage]    = useState(1)
  const [coreRows,    setCoreRows]    = useState<CoreVehicleRow[]>([])
  const [coreTotal,   setCoreTotal]   = useState(0)
  const [coreLoading, setCoreLoading] = useState(true)

  // OEM Fitment tab state
  const [fitSearch,  setFitSearch]  = useState('')
  const [fitPage,    setFitPage]    = useState(1)
  const [fitRows,    setFitRows]    = useState<OemFitmentRow[]>([])
  const [fitTotal,   setFitTotal]   = useState(0)
  const [fitLoading, setFitLoading] = useState(false)
  const [fitLoaded,  setFitLoaded]  = useState(false)

  async function loadCore(page = corePage, search = coreSearch) {
    setCoreLoading(true)
    try {
      const r = await getVehicleDataCore(page, PAGE_SIZE, search)
      setCoreRows(r.items)
      setCoreTotal(r.total)
    } catch { /* ignore */ }
    finally { setCoreLoading(false) }
  }

  async function loadFitment(page = fitPage, search = fitSearch) {
    setFitLoading(true)
    try {
      const r = await getVehicleDataOemFitment(page, PAGE_SIZE, search)
      setFitRows(r.items)
      setFitTotal(r.total)
    } catch { /* ignore */ }
    finally { setFitLoading(false); setFitLoaded(true) }
  }

  useEffect(() => { loadCore(1, coreSearch) }, [])

  useEffect(() => {
    const t = setTimeout(() => loadCore(1, coreSearch), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coreSearch])

  useEffect(() => {
    if (tab !== 'fitment') return
    const t = setTimeout(() => loadFitment(1, fitSearch), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitSearch, tab])

  function switchTab(next: Tab) {
    setTab(next)
    if (next === 'fitment' && !fitLoaded) loadFitment(1, '')
  }

  return (
    <AdminLayout>
      <div style={{ padding: '1.5rem', maxWidth: 1200, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h1 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--adm-text-1)' }}>Vehicle Data</h1>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--adm-sep)' }}>
          <TabButton active={tab === 'core'}    onClick={() => switchTab('core')}    label="Core Dataset" count={coreTotal} />
          <TabButton active={tab === 'fitment'} onClick={() => switchTab('fitment')} label="OEM Fitment"  count={fitLoaded ? fitTotal : undefined} />
        </div>

        {tab === 'core' && (
          <VehicleTable
            searchPlaceholder="Search core dataset…"
            search={coreSearch}
            onSearch={v => { setCoreSearch(v); setCorePage(1) }}
            loading={coreLoading}
            total={coreTotal}
            page={corePage}
            onPage={p => { setCorePage(p); loadCore(p, coreSearch) }}
          >
            <thead>
              <tr style={{ background: 'var(--adm-thead-bg)' }}>
                {['Make', 'Model', 'Year', 'Engine CC', 'Fuel', 'Source'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!coreLoading && coreRows.length === 0 && (
                <tr><td colSpan={6} style={emptyStyle}>{coreSearch ? 'No matches found.' : 'No rows.'}</td></tr>
              )}
              {!coreLoading && coreRows.map((r, i) => (
                <tr key={r.id} style={rowStyle(i)}>
                  <td style={tdStyle}>{r.make}</td>
                  <td style={tdStyle}>{r.model}</td>
                  <td style={tdStyle}>{r.year}</td>
                  <td style={tdStyle}>{r.engine_capacity ?? '–'}</td>
                  <td style={tdStyle}>{r.fuel ?? '–'}</td>
                  <td style={{ ...tdStyle, color: 'var(--adm-text-2)', fontSize: '0.72rem' }}>{r.source ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </VehicleTable>
        )}

        {tab === 'fitment' && (
          <VehicleTable
            searchPlaceholder="Search OEM fitment…"
            search={fitSearch}
            onSearch={v => { setFitSearch(v); setFitPage(1) }}
            loading={fitLoading}
            total={fitTotal}
            page={fitPage}
            onPage={p => { setFitPage(p); loadFitment(p, fitSearch) }}
          >
            <thead>
              <tr style={{ background: 'var(--adm-thead-bg)' }}>
                {['Make', 'Model', 'Years', 'Ah', 'Technology', 'Dimensions', 'Cylinder CC'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!fitLoading && fitRows.length === 0 && (
                <tr><td colSpan={7} style={emptyStyle}>{fitSearch ? 'No matches found.' : 'No rows.'}</td></tr>
              )}
              {!fitLoading && fitRows.map(r => (
                <tr key={r.id} style={rowStyle(r.id)}>
                  <td style={tdStyle}>{r.make}</td>
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
          </VehicleTable>
        )}

      </div>
    </AdminLayout>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function TabButton({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.6rem 1rem', background: 'none', border: 'none', cursor: 'pointer',
        borderBottom: active ? '2px solid #CC0000' : '2px solid transparent',
        fontSize: '0.85rem', fontWeight: 700,
        color: active ? 'var(--adm-text-1)' : 'var(--adm-text-2)',
        marginBottom: -1,
      }}
    >
      {label}
      {count != null && (
        <span style={{ background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-2)', fontSize: '0.68rem', fontWeight: 700, padding: '0.1rem 0.45rem', borderRadius: 20 }}>
          {count.toLocaleString()}
        </span>
      )}
    </button>
  )
}

function VehicleTable({
  searchPlaceholder, search, onSearch, loading, total, page, onPage, children,
}: {
  searchPlaceholder: string
  search:   string
  onSearch: (v: string) => void
  loading:  boolean
  total:    number
  page:     number
  onPage:   (p: number) => void
  children: React.ReactNode
}) {
  return (
    <div style={{ ...CARD, padding: 0, overflow: 'hidden' }}>
      <div style={{ padding: '0.75rem 1.25rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', justifyContent: 'flex-end' }}>
        <input
          value={search}
          onChange={e => onSearch(e.target.value)}
          placeholder={searchPlaceholder}
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
          {children}
        </table>
        {loading && (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>Loading…</div>
        )}
      </div>
      {total > PAGE_SIZE && (
        <div style={{ padding: '0.75rem 1.25rem', borderTop: '1px solid var(--adm-sep)', display: 'flex', gap: '0.5rem', alignItems: 'center', justifyContent: 'flex-end' }}>
          <button disabled={page === 1} onClick={() => onPage(page - 1)} style={pagBtn(page === 1)}>← Prev</button>
          <span style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)' }}>
            Page {page} / {Math.ceil(total / PAGE_SIZE)}
          </span>
          <button disabled={page * PAGE_SIZE >= total} onClick={() => onPage(page + 1)} style={pagBtn(page * PAGE_SIZE >= total)}>Next →</button>
        </div>
      )}
    </div>
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
