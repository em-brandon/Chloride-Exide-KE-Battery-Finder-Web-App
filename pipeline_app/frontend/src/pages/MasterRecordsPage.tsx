import { useState, useEffect, useCallback } from 'react'
import { PencilSquareIcon, TrashIcon, XMarkIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/react/24/solid'
import { api, type MasterRecord } from '../lib/api'

const R = '#CC0000'

const CARD: React.CSSProperties = {
  background: '#fff', borderRadius: 14, border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)', padding: '1.25rem',
}

export function MasterRecordsPage() {
  const [records, setRecords]   = useState<MasterRecord[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [search, setSearch]     = useState('')
  const [loading, setLoading]   = useState(true)
  const [coverage, setCoverage] = useState<Record<string, unknown> | null>(null)

  const [editRow, setEditRow]         = useState<MasterRecord | null>(null)
  const [editAh, setEditAh]           = useState('')
  const [editTech, setEditTech]       = useState('')
  const [editBc, setEditBc]           = useState('')
  const [editScope, setEditScope]     = useState<'single' | 'bucket'>('single')
  const [savingEdit, setSavingEdit]   = useState(false)
  const [saveResult, setSaveResult]   = useState<{ rows_updated: number } | null>(null)

  const [deletingId, setDeletingId]   = useState<number | null>(null)

  const PAGE_SIZE = 50

  const load = useCallback(async (p: number, q: string) => {
    setLoading(true)
    try {
      const res = await api.wvMatched(p, PAGE_SIZE, q)
      setRecords(res.items)
      setTotal(res.total)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(1, '')
    api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
  }, [load])

  async function handleSearch(q: string) {
    setSearch(q)
    setPage(1)
    await load(1, q)
  }

  async function handlePage(p: number) {
    setPage(p)
    await load(p, search)
  }

  function openEdit(row: MasterRecord) {
    setEditRow(row)
    setEditAh(String(row.ah ?? ''))
    setEditTech(row.technology ?? 'MF')
    setEditBc(row.battery_code ?? '')
    setEditScope('single')
    setSaveResult(null)
  }

  async function handleSaveEdit() {
    if (!editRow) return
    setSavingEdit(true)
    try {
      const res = await api.patchMaster(editRow.id, {
        ah: editAh ? parseFloat(editAh) : null,
        technology: editTech || null,
        battery_code: editBc || null,
        scope: editScope,
      })
      setSaveResult({ rows_updated: res.rows_updated })
      await load(page, search)
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
      if (editScope === 'single') {
        setEditRow(null)
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSavingEdit(false)
    }
  }

  async function handleDelete(row: MasterRecord) {
    if (!confirm(`Delete ${row.make_n} ${row.model_n} ${row.year} from master? This cannot be undone.`)) return
    setDeletingId(row.id)
    try {
      await api.deleteMaster(row.id)
      setRecords(prev => prev.filter(r => r.id !== row.id))
      setTotal(prev => prev - 1)
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeletingId(null) }
  }

  const totalPages = Math.ceil((total || 1) / PAGE_SIZE)

  // Bucket range label for the scope selector
  const bucketLabel = editRow
    ? (() => {
        const bs = Math.floor(editRow.year / 5) * 5
        return `${bs}–${bs + 4}`
      })()
    : ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
        All committed web-validated battery records. Edit individual years or apply changes
        across a 5-year bucket in one step.
      </div>

      {/* Coverage strip */}
      {coverage && (
        <div style={{ ...CARD, padding: '0.85rem 1.25rem' }}>
          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', alignItems: 'center' }}>
            {([
              ['Total Combos',   coverage.total,        '#6b7280'],
              ['Matched',        coverage.matched,       '#22c55e'],
              ['Unmatched',      coverage.unmatched,     R],
              ['Master Records', coverage.master_count,  '#6366f1'],
            ] as [string, unknown, string][]).map(([label, val, color]) => (
              <div key={label} style={{ textAlign: 'center', minWidth: 70 }}>
                <div style={{ fontSize: '1.35rem', fontWeight: 800, color }}>{String(val ?? '–')}</div>
                <div style={{ fontSize: '0.68rem', color: '#9ca3af', marginTop: 2 }}>{label}</div>
              </div>
            ))}
            <div style={{ marginLeft: 'auto' }}>
              <div style={{
                height: 8, width: 160, background: '#e2e4e9', borderRadius: 99, overflow: 'hidden',
              }}>
                <div style={{
                  height: 8, borderRadius: 99,
                  background: Number(coverage.pct_matched) > 80 ? '#22c55e' : Number(coverage.pct_matched) > 50 ? '#f59e0b' : R,
                  width: `${Number(coverage.pct_matched) || 0}%`,
                  transition: 'width 0.4s',
                }} />
              </div>
              <div style={{ fontSize: '0.68rem', color: '#9ca3af', marginTop: 4, textAlign: 'right' }}>
                {Number(coverage.pct_matched) || 0}% covered
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Search + pagination header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <input
          placeholder="Search make, model…"
          value={search}
          onChange={e => handleSearch(e.target.value)}
          style={{
            flex: 1, minWidth: 200,
            padding: '0.45rem 0.75rem', borderRadius: 8,
            border: '1px solid #d1d5db', fontSize: '0.82rem',
          }}
        />
        <span style={{ fontSize: '0.75rem', color: '#6b7280', whiteSpace: 'nowrap' }}>
          {total.toLocaleString()} records
        </span>
        <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
          <button disabled={page === 1} onClick={() => handlePage(page - 1)} style={paginationBtn(page === 1)}>← Prev</button>
          <span style={{ fontSize: '0.75rem', color: '#6b7280', whiteSpace: 'nowrap' }}>
            Page {page} / {totalPages}
          </span>
          <button disabled={page >= totalPages} onClick={() => handlePage(page + 1)} style={paginationBtn(page >= totalPages)}>Next →</button>
        </div>
      </div>

      {/* Table */}
      <div style={CARD}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: '#9ca3af', fontSize: '0.82rem' }}>Loading…</div>
        ) : records.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: '#9ca3af', fontSize: '0.82rem' }}>
            No records found. Run Phase 2 and commit staging to populate the master table.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: '#f8f9fb' }}>
                  {['Make', 'Model', 'Year', 'Battery Code', 'Ah', 'Technology', 'Source', 'Validated', ''].map(h => (
                    <th key={h} style={{
                      padding: '0.5rem 0.65rem', textAlign: 'left',
                      fontWeight: 600, color: '#374151',
                      borderBottom: '2px solid #e2e4e9', whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map((row, i) => {
                  const src = row.source ?? ''
                  const srcColor = src === 'brave' ? '#b45309' : src === 'tavily' ? '#4f46e5' : src === 'duckduckgo' ? '#2563eb' : src === 'carquery' ? '#15803d' : '#6b7280'
                  const srcBg    = src === 'brave' ? '#fef3c7' : src === 'tavily' ? '#ede9fe' : src === 'duckduckgo' ? '#dbeafe' : src === 'carquery' ? '#dcfce7' : '#f3f4f6'
                  return (
                    <tr key={row.id} style={{ background: i % 2 === 0 ? '#fff' : '#fafafa', borderBottom: '1px solid #f1f3f5' }}>
                      <td style={{ padding: '0.45rem 0.65rem', color: '#111827', fontWeight: 500 }}>{row.make_n}</td>
                      <td style={{ padding: '0.45rem 0.65rem', color: '#111827' }}>{row.model_n}</td>
                      <td style={{ padding: '0.45rem 0.65rem', color: '#374151' }}>{row.year}</td>
                      <td style={{ padding: '0.45rem 0.65rem', fontFamily: 'monospace', fontSize: '0.73rem', color: '#374151' }}>{row.battery_code ?? '—'}</td>
                      <td style={{ padding: '0.45rem 0.65rem', color: '#374151', fontWeight: 600 }}>{row.ah != null ? `${row.ah} Ah` : '—'}</td>
                      <td style={{ padding: '0.45rem 0.65rem' }}>
                        {row.technology
                          ? <span style={{ background: '#e0e7ff', color: '#3730a3', padding: '0.1rem 0.4rem', borderRadius: 6, fontSize: '0.68rem', fontWeight: 700 }}>{row.technology}</span>
                          : <span style={{ color: '#9ca3af' }}>—</span>
                        }
                      </td>
                      <td style={{ padding: '0.45rem 0.65rem' }}>
                        <span style={{ background: srcBg, color: srcColor, borderRadius: 99, padding: '0.15rem 0.5rem', fontSize: '0.68rem', fontWeight: 600, textTransform: 'capitalize' }}>{src || '—'}</span>
                      </td>
                      <td style={{ padding: '0.45rem 0.65rem', color: '#9ca3af', fontSize: '0.72rem' }}>
                        {row.validated_at ? new Date(row.validated_at).toLocaleDateString() : '—'}
                      </td>
                      <td style={{ padding: '0.45rem 0.65rem' }}>
                        <div style={{ display: 'flex', gap: '0.2rem' }}>
                          <button
                            onClick={() => openEdit(row)}
                            title="Edit"
                            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.2rem', color: '#6b7280', display: 'flex', borderRadius: 4 }}>
                            <PencilSquareIcon style={{ width: 15, height: 15 }} />
                          </button>
                          <button
                            onClick={() => handleDelete(row)}
                            disabled={deletingId === row.id}
                            title="Delete"
                            style={{ background: 'none', border: 'none', cursor: deletingId === row.id ? 'not-allowed' : 'pointer', padding: '0.2rem', color: deletingId === row.id ? '#9ca3af' : R, display: 'flex', borderRadius: 4 }}>
                            <TrashIcon style={{ width: 15, height: 15 }} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Bottom pagination */}
        {!loading && records.length > 0 && (
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
            <button disabled={page === 1} onClick={() => handlePage(page - 1)} style={paginationBtn(page === 1)}>← Prev</button>
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>Page {page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => handlePage(page + 1)} style={paginationBtn(page >= totalPages)}>Next →</button>
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editRow && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 200,
          display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem',
        }} onMouseDown={e => { if (e.target === e.currentTarget) setEditRow(null) }}>
          <div style={{
            background: '#fff', borderRadius: 16, border: '1px solid #e2e4e9',
            boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
            padding: '1.5rem', width: '100%', maxWidth: 440,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
              <div>
                <h3 style={{ fontWeight: 800, fontSize: '1rem', color: '#111827', margin: 0 }}>
                  {editRow.make_n} {editRow.model_n} {editRow.year}
                </h3>
                <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: 2 }}>Edit master record</div>
              </div>
              <button onClick={() => setEditRow(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', display: 'flex', padding: '0.2rem' }}>
                <XMarkIcon style={{ width: 20, height: 20 }} />
              </button>
            </div>

            {/* Scope selector */}
            <div style={{
              background: '#f8f9fb', border: '1px solid #e2e4e9',
              borderRadius: 10, padding: '0.75rem', marginBottom: '0.85rem',
            }}>
              <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#9ca3af', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
                Update scope
              </div>
              {(['single', 'bucket'] as const).map(s => {
                const bs = Math.floor(editRow.year / 5) * 5
                const label = s === 'single'
                  ? `This year only (${editRow.year})`
                  : `All ${bucketLabel} bucket records (${bs}–${bs + 4})`
                return (
                  <label key={s} style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    fontSize: '0.82rem', color: '#374151', cursor: 'pointer',
                    padding: '0.25rem 0', lineHeight: 1.4,
                  }}>
                    <input
                      type="radio"
                      name="editScope"
                      value={s}
                      checked={editScope === s}
                      onChange={() => { setEditScope(s); setSaveResult(null) }}
                      style={{ accentColor: R, width: 15, height: 15, flexShrink: 0 }}
                    />
                    <span style={{ fontWeight: editScope === s ? 600 : 400 }}>{label}</span>
                    {s === 'bucket' && (
                      <span style={{ background: '#fef3c7', color: '#92400e', fontSize: '0.6rem', fontWeight: 700, borderRadius: 99, padding: '0.1rem 0.4rem', flexShrink: 0 }}>
                        Bulk
                      </span>
                    )}
                  </label>
                )
              })}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Battery Code</label>
                <input value={editBc} onChange={e => setEditBc(e.target.value)} placeholder="e.g. NS60L"
                  style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', fontFamily: 'monospace', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Ah Capacity</label>
                <input type="number" value={editAh} onChange={e => setEditAh(e.target.value)} min={20} max={250}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Technology</label>
                <select value={editTech} onChange={e => setEditTech(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', boxSizing: 'border-box' }}>
                  {['MF', 'AGM', 'EFB', 'GEL', 'WET'].map(t => <option key={t}>{t}</option>)}
                </select>
              </div>

              {saveResult && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: '#dcfce7', border: '1px solid #bbf7d0', borderRadius: 8, padding: '0.5rem 0.75rem', fontSize: '0.78rem', color: '#15803d' }}>
                  <CheckCircleIcon style={{ width: 14, height: 14, flexShrink: 0 }} />
                  Updated {saveResult.rows_updated} record{saveResult.rows_updated !== 1 ? 's' : ''}
                  {editScope === 'bucket' && ` across ${bucketLabel} bucket`}
                </div>
              )}

              {editScope === 'bucket' && !saveResult && (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.4rem', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '0.5rem 0.75rem', fontSize: '0.75rem', color: '#92400e' }}>
                  <ExclamationTriangleIcon style={{ width: 13, height: 13, flexShrink: 0, marginTop: 1 }} />
                  This will update all existing {bucketLabel} records for {editRow.make_n} {editRow.model_n}.
                </div>
              )}

              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.25rem' }}>
                <button onClick={() => setEditRow(null)} style={btnStyle('#f3f4f6', '#374151')}>
                  {saveResult ? 'Close' : 'Cancel'}
                </button>
                {!saveResult && (
                  <button onClick={handleSaveEdit} disabled={savingEdit} style={btnStyle(R, '#fff')}>
                    {savingEdit ? 'Saving…' : editScope === 'bucket' ? `Update ${bucketLabel} bucket` : 'Save'}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function btnStyle(bg: string, color: string, border?: string): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
    background: bg, color, border: border ?? 'none', borderRadius: 8,
    padding: '0.45rem 1rem', fontWeight: 700, fontSize: '0.82rem', cursor: 'pointer',
    whiteSpace: 'nowrap',
  }
}

function paginationBtn(disabled: boolean): React.CSSProperties {
  return {
    background: '#f3f4f6', border: '1px solid #e2e4e9', borderRadius: 8,
    padding: '0.3rem 0.65rem', fontSize: '0.75rem', cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1, color: '#374151', fontWeight: 600,
  }
}
