import { useState, useEffect, useCallback, useRef, type DragEvent, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BoltIcon, MagnifyingGlassIcon, ArrowUpTrayIcon, ArrowDownTrayIcon, PlusIcon, XMarkIcon, ChevronLeftIcon, ChevronRightIcon } from '@heroicons/react/20/solid'
import {
  fetchBatteries,
  addBattery,
  updateBattery,
  deleteBattery,
  uploadBatteriesExcel,
  exportBatteriesUrl,
  type BatteryRow,
  type BatteryPayload,
  type UploadResult,
} from '@/lib/adminApi'
import AdminLayout from '@/components/admin/AdminLayout'

// ── Design tokens ────────────────────────────────────────────────────────────
const R   = '#CC0000'
const RD  = '#990000'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}
const INPUT: React.CSSProperties = {
  width: '100%',
  borderRadius: '8px',
  border: '1px solid #d1d5db',
  background: '#fff',
  padding: '0.45rem 0.75rem',
  fontSize: '0.85rem',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
  outline: 'none',
  boxSizing: 'border-box',
}

// ---------------------------------------------------------------------------
// Battery form (add + edit)
// ---------------------------------------------------------------------------

const EMPTY_FORM: BatteryPayload = {
  battery_code: '',
  model_key: '',
  ah: 0,
  cca_en: null,
  technology: '',
}

function BatteryForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: BatteryPayload
  onSave: (p: BatteryPayload) => Promise<void>
  onCancel: () => void
}) {
  const [form, setForm] = useState<BatteryPayload>(initial)
  const [err, setErr]   = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function set(key: keyof BatteryPayload, value: string) {
    setForm(f => ({ ...f, [key]: value }))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await onSave({
        battery_code: form.battery_code.toUpperCase().trim(),
        model_key:    form.model_key.toUpperCase().trim(),
        ah:           Number(form.ah),
        cca_en:       form.cca_en !== null && String(form.cca_en) !== '' ? Number(form.cca_en) : null,
        technology:   form.technology.toUpperCase().trim(),
      })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
      setBusy(false)
    }
  }

  const field = (label: string, key: keyof BatteryPayload, type = 'text', required = true) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'rgba(107,114,128,0.9)', letterSpacing: '0.04em' }}>
        {label}{required && <span style={{ color: R, marginLeft: '2px' }}>*</span>}
      </label>
      <input
        type={type}
        required={required}
        step={type === 'number' ? 'any' : undefined}
        value={form[key] ?? ''}
        onChange={e => set(key, e.target.value)}
        style={INPUT}
        onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = `0 0 0 3px rgba(204,0,0,0.12)` }}
        onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }}
      />
    </div>
  )

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
      {err && (
        <div style={{ background: '#fff5f5', border: '1px solid #f5c6c6', borderRadius: '8px', padding: '0.6rem 0.85rem', fontSize: '0.8rem', color: R }}>
          {err}
        </div>
      )}
      {field('Battery Code', 'battery_code')}
      {field('Model Key', 'model_key')}
      {field('Ah (capacity)', 'ah', 'number')}
      {field('CCA EN (optional)', 'cca_en', 'number', false)}
      {field('Technology', 'technology')}
      <div style={{ display: 'flex', gap: '0.6rem', paddingTop: '0.25rem' }}>
        <button
          type="submit"
          disabled={busy}
          style={{ flex: 1, background: busy ? '#e88' : R, color: '#fff', border: 'none', borderRadius: '8px', padding: '0.55rem', fontSize: '0.85rem', fontWeight: 700, cursor: busy ? 'not-allowed' : 'pointer', transition: 'background 0.15s' }}
          onMouseEnter={e => { if (!busy) e.currentTarget.style.background = RD }}
          onMouseLeave={e => { if (!busy) e.currentTarget.style.background = R }}
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{ flex: 1, background: '#f4f5f7', color: 'rgba(17,24,39,0.7)', border: '1px solid #e2e4e9', borderRadius: '8px', padding: '0.55rem', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer' }}
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Excel dropzone
// ---------------------------------------------------------------------------

function ExcelDropzone({ onDone }: { onDone: () => void }) {
  const [dragging, setDragging]   = useState(false)
  const [uploading, setUploading] = useState(false)
  const [result, setResult]       = useState<UploadResult | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    if (!file.name.endsWith('.xlsx')) {
      setError('Only .xlsx files are accepted')
      return
    }
    setError(null)
    setResult(null)
    setUploading(true)
    try {
      const r = await uploadBatteriesExcel(file)
      setResult(r)
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? R : '#d1d5db'}`,
          borderRadius: '12px',
          padding: '2rem',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragging ? '#fff5f5' : '#fafafa',
          transition: 'all 0.2s',
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          style={{ display: 'none' }}
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
        />
        <ArrowUpTrayIcon style={{ width: 28, height: 28, color: dragging ? R : 'rgba(107,114,128,0.5)', margin: '0 auto 0.6rem', display: 'block' }} />
        {uploading ? (
          <p style={{ fontSize: '0.85rem', color: 'rgba(107,114,128,0.8)' }}>Uploading and processing…</p>
        ) : (
          <>
            <p style={{ fontSize: '0.85rem', fontWeight: 600, color: 'rgba(17,24,39,0.75)', margin: 0 }}>
              Drop a <strong style={{ color: R }}>.xlsx</strong> file here, or click to browse
            </p>
            <p style={{ fontSize: '0.75rem', color: 'rgba(107,114,128,0.6)', marginTop: '0.3rem' }}>
              Required columns: battery_code, model_key, ah, technology
            </p>
          </>
        )}
      </div>

      {error && (
        <div style={{ background: '#fff5f5', border: '1px solid #f5c6c6', borderRadius: '10px', padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ background: '#f8f9fb', border: '1px solid #e2e4e9', borderRadius: '10px', padding: '1rem', fontSize: '0.82rem' }}>
          <p style={{ fontWeight: 700, color: 'rgba(17,24,39,0.85)', marginBottom: '0.6rem' }}>Upload complete</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {[
              { label: `Inserted: ${result.inserted}`,          bg: '#f0fdf4', color: '#15803d', border: '#bbf7d0' },
              { label: `Updated: ${result.updated}`,            bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
              { label: `Unchanged: ${result.skipped_unchanged}`,bg: '#f8f9fb', color: 'rgba(107,114,128,0.8)', border: '#e2e4e9' },
              { label: `Rejected: ${result.rejected}`,          bg: '#fff5f5', color: R,          border: '#f5c6c6' },
            ].map(c => (
              <div key={c.label} style={{ borderRadius: '7px', background: c.bg, border: `1px solid ${c.border}`, padding: '0.4rem 0.6rem', fontSize: '0.75rem', fontWeight: 700, color: c.color, whiteSpace: 'nowrap' }}>{c.label}</div>
            ))}
          </div>
          {result.errors.length > 0 && (
            <details style={{ marginTop: '0.6rem' }}>
              <summary style={{ cursor: 'pointer', color: R, fontWeight: 600, fontSize: '0.78rem' }}>
                {result.errors.length} row error{result.errors.length > 1 ? 's' : ''}
              </summary>
              <ul style={{ marginTop: '0.5rem', paddingLeft: '1rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                {result.errors.map((e, i) => (
                  <li key={i} style={{ fontSize: '0.75rem', color: 'rgba(107,114,128,0.8)' }}>
                    Row {e.row} ({e.battery_code}): {e.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AdminBatteries() {
  const [searchParams] = useSearchParams()
  const manage = searchParams.get('manage') === 'true'

  const [items, setItems]       = useState<BatteryRow[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [search, setSearch]     = useState('')
  const [techFilter, setTech]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [showAdd, setShowAdd]   = useState(false)
  const [editing, setEditing]   = useState<BatteryRow | null>(null)
  const [showUpload, setShowUp] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)

  const PAGE_SIZE = 50

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetchBatteries(page, PAGE_SIZE, search || undefined, techFilter || undefined)
      setItems(r.items)
      setTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [page, search, techFilter])

  useEffect(() => { load() }, [load])

  async function handleAdd(payload: BatteryPayload) {
    await addBattery(payload)
    setShowAdd(false)
    load()
  }

  async function handleUpdate(payload: BatteryPayload) {
    if (!editing) return
    await updateBattery(editing.id, payload)
    setEditing(null)
    load()
  }

  async function handleDelete(id: number) {
    setDeleting(id)
    try {
      await deleteBattery(id)
      load()
    } finally {
      setDeleting(null)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const techColors: Record<string, { bg: string; color: string; border: string }> = {
    EFB:  { bg: '#fff7ed', color: '#c2410c', border: '#fed7aa' },
    AGM:  { bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
    GEL:  { bg: '#f0fdf4', color: '#15803d', border: '#bbf7d0' },
    FLA:  { bg: '#faf5ff', color: '#7e22ce', border: '#e9d5ff' },
    VRLA: { bg: '#fff5f5', color: R,          border: '#f5c6c6' },
  }
  function techBadge(tech: string) {
    const c = techColors[tech.toUpperCase()] ?? { bg: '#f4f5f7', color: 'rgba(107,114,128,0.85)', border: '#e2e4e9' }
    return (
      <span style={{ display: 'inline-block', padding: '0.18rem 0.65rem', borderRadius: '99px', background: c.bg, color: c.color, border: `1px solid ${c.border}`, fontSize: '0.7rem', fontWeight: 700 }}>
        {tech}
      </span>
    )
  }

  return (
    <AdminLayout>

      {/* Nav */}
      <header style={{ background: '#fff', borderBottom: '1px solid #e2e4e9', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BoltIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>Battery Specs</span>
        </div>
        <span style={{ marginLeft: '0.5rem', fontSize: '0.72rem', color: 'rgba(107,114,128,0.6)', background: '#f4f5f7', borderRadius: '99px', padding: '0.2rem 0.7rem', border: '1px solid #e2e4e9' }}>
          {total.toLocaleString()} records
        </span>
      </header>

      <main style={{ maxWidth: '1100px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

        {/* Toolbar */}
        <div style={{ ...CARD, padding: '1rem 1.25rem', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
          {/* Search */}
          <div style={{ position: 'relative', flex: '1 1 200px', minWidth: '180px' }}>
            <MagnifyingGlassIcon style={{ width: 14, height: 14, color: 'rgba(107,114,128,0.5)', position: 'absolute', left: '0.65rem', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
            <input
              type="search"
              placeholder="Search code or model…"
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1) }}
              style={{ ...INPUT, paddingLeft: '2rem' }}
              onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = `0 0 0 3px rgba(204,0,0,0.1)` }}
              onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }}
            />
          </div>
          <input
            type="text"
            placeholder="Filter by technology…"
            value={techFilter}
            onChange={e => { setTech(e.target.value); setPage(1) }}
            style={{ ...INPUT, flex: '1 1 160px', minWidth: '140px' }}
            onFocus={e => { e.currentTarget.style.borderColor = R; e.currentTarget.style.boxShadow = `0 0 0 3px rgba(204,0,0,0.1)` }}
            onBlur={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.boxShadow = 'none' }}
          />

          {manage && (
            <div style={{ display: 'flex', gap: '0.5rem', marginLeft: 'auto', flexWrap: 'wrap' }}>
              <button
                onClick={() => { setShowAdd(true); setEditing(null) }}
                style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: R, color: '#fff', border: 'none', borderRadius: '8px', padding: '0.45rem 1rem', fontSize: '0.82rem', fontWeight: 700, cursor: 'pointer', transition: 'background 0.15s' }}
                onMouseEnter={e => (e.currentTarget.style.background = RD)}
                onMouseLeave={e => (e.currentTarget.style.background = R)}
              >
                <PlusIcon style={{ width: 14, height: 14 }} /> Add Battery
              </button>
              <button
                onClick={() => setShowUp(u => !u)}
                style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: showUpload ? '#f4f5f7' : '#fff', color: 'rgba(17,24,39,0.75)', border: '1px solid #e2e4e9', borderRadius: '8px', padding: '0.45rem 1rem', fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer' }}
              >
                <ArrowUpTrayIcon style={{ width: 14, height: 14 }} /> {showUpload ? 'Hide Upload' : 'Upload .xlsx'}
              </button>
              <a
                href={exportBatteriesUrl()}
                download
                style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: '#fff', color: 'rgba(17,24,39,0.75)', border: '1px solid #e2e4e9', borderRadius: '8px', padding: '0.45rem 1rem', fontSize: '0.82rem', fontWeight: 600, textDecoration: 'none' }}
              >
                <ArrowDownTrayIcon style={{ width: 14, height: 14 }} /> Export .xlsx
              </a>
            </div>
          )}
        </div>

        {/* Upload zone */}
        {showUpload && (
          <div style={{ ...CARD, padding: '1.5rem', borderTop: `3px solid ${R}` }}>
            <h2 style={{ fontSize: '0.82rem', fontWeight: 700, color: 'rgba(17,24,39,0.8)', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <ArrowUpTrayIcon style={{ width: 14, height: 14, color: R }} /> Bulk Upload
            </h2>
            <ExcelDropzone onDone={() => { setShowUp(false); load() }} />
          </div>
        )}

        {/* Add form panel */}
        {showAdd && (
          <div style={{ ...CARD, padding: '1.5rem', maxWidth: '400px', borderTop: `3px solid ${R}` }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '0.88rem', fontWeight: 700, color: 'rgba(17,24,39,0.85)', margin: 0 }}>Add Battery</h2>
              <button onClick={() => setShowAdd(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: '2px' }}>
                <XMarkIcon style={{ width: 16, height: 16 }} />
              </button>
            </div>
            <BatteryForm initial={EMPTY_FORM} onSave={handleAdd} onCancel={() => setShowAdd(false)} />
          </div>
        )}

        {/* Edit modal */}
        {editing && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: '1rem' }}>
            <div style={{ ...CARD, padding: '1.75rem', width: '100%', maxWidth: '400px', maxHeight: '90vh', overflow: 'auto' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'rgba(17,24,39,0.88)', margin: 0 }}>Edit Battery</h2>
                <button onClick={() => setEditing(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: '2px' }}>
                  <XMarkIcon style={{ width: 18, height: 18 }} />
                </button>
              </div>
              <BatteryForm
                initial={{
                  battery_code: editing.battery_code,
                  model_key:    editing.model_key,
                  ah:           editing.ah,
                  cca_en:       editing.cca_en,
                  technology:   editing.technology,
                }}
                onSave={handleUpdate}
                onCancel={() => setEditing(null)}
              />
            </div>
          </div>
        )}

        {/* Table */}
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ background: '#f8f9fb', borderBottom: '2px solid #e2e4e9' }}>
                  {(manage ? ['Battery Code', 'Model Key', 'Ah', 'CCA EN', 'Technology', 'Actions'] : ['Battery Code', 'Model Key', 'Ah', 'CCA EN', 'Technology']).map(h => (
                    <th key={h} style={{ padding: '0.8rem 1.1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={manage ? 6 : 5} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>
                      Loading…
                    </td>
                  </tr>
                )}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={manage ? 6 : 5} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>
                      No batteries found
                    </td>
                  </tr>
                )}
                {!loading && items.map((b, i) => (
                  <tr
                    key={b.id}
                    style={{ borderTop: i > 0 ? '1px solid #f0f1f4' : 'none', transition: 'background 0.1s' }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#fff8f8')}
                    onMouseLeave={e => (e.currentTarget.style.background = '#fff')}
                  >
                    <td style={{ padding: '0.8rem 1.1rem', fontFamily: 'monospace', fontWeight: 700, color: R, fontSize: '0.8rem' }}>{b.battery_code}</td>
                    <td style={{ padding: '0.8rem 1.1rem', fontFamily: 'monospace', fontSize: '0.78rem', color: 'rgba(17,24,39,0.7)' }}>{b.model_key}</td>
                    <td style={{ padding: '0.8rem 1.1rem', fontWeight: 600, color: 'rgba(17,24,39,0.8)' }}>{b.ah}</td>
                    <td style={{ padding: '0.8rem 1.1rem', color: b.cca_en ? 'rgba(17,24,39,0.7)' : 'rgba(107,114,128,0.4)' }}>{b.cca_en ?? '—'}</td>
                    <td style={{ padding: '0.8rem 1.1rem' }}>{techBadge(b.technology)}</td>
                    {manage && (
                      <td style={{ padding: '0.8rem 1.1rem' }}>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                          <button
                            onClick={() => { setEditing(b); setShowAdd(false) }}
                            style={{ fontSize: '0.75rem', fontWeight: 600, color: '#1d4ed8', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px', padding: '0.25rem 0.65rem', cursor: 'pointer' }}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => {
                              if (window.confirm(`Delete ${b.battery_code}? This is reversible from the audit log.`)) {
                                handleDelete(b.id)
                              }
                            }}
                            disabled={deleting === b.id}
                            style={{ fontSize: '0.75rem', fontWeight: 600, color: deleting === b.id ? 'rgba(107,114,128,0.4)' : R, background: deleting === b.id ? '#f8f9fb' : '#fff5f5', border: `1px solid ${deleting === b.id ? '#e2e4e9' : '#f5c6c6'}`, borderRadius: '6px', padding: '0.25rem 0.65rem', cursor: deleting === b.id ? 'not-allowed' : 'pointer' }}
                          >
                            {deleting === b.id ? '…' : 'Delete'}
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.78rem', color: 'rgba(107,114,128,0.8)' }}>
            <span>{total.toLocaleString()} total records</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid #e2e4e9', background: '#fff', fontSize: '0.78rem', fontWeight: 600, cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.4 : 1 }}
              >
                <ChevronLeftIcon style={{ width: 13, height: 13 }} /> Prev
              </button>
              <span style={{ padding: '0 0.5rem', fontWeight: 600, color: 'rgba(17,24,39,0.7)' }}>
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid #e2e4e9', background: '#fff', fontSize: '0.78rem', fontWeight: 600, cursor: page === totalPages ? 'not-allowed' : 'pointer', opacity: page === totalPages ? 0.4 : 1 }}
              >
                Next <ChevronRightIcon style={{ width: 13, height: 13 }} />
              </button>
            </div>
          </div>
        )}
      </main>
    </AdminLayout>
  )
}
