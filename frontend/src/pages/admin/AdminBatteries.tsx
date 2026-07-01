import { useState, useEffect, useCallback, useRef, type DragEvent, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BoltIcon, MagnifyingGlassIcon, ArrowUpTrayIcon, ArrowDownTrayIcon, PlusIcon, XMarkIcon, ChevronLeftIcon, ChevronRightIcon } from '@heroicons/react/20/solid'
import exideMaxLogo    from '@/assets/exide-max-logo.webp'
import sparkLogo       from '@/assets/spark-logo.webp'
import powerlastLogo   from '@/assets/powerlast-logo.webp'
import supremeLogo     from '@/assets/supreme-logo.webp'
import sebangLogo      from '@/assets/sebang-logo.webp'
import exideAgmLogo    from '@/assets/exide-agm-logo.webp'
import sbFloodedLogo   from '@/assets/sb-flooded-logo.webp'
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
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}
const INPUT: React.CSSProperties = {
  width: '100%',
  borderRadius: '8px',
  border: '1px solid var(--adm-input-border)',
  background: 'var(--adm-input-bg)',
  color: 'var(--adm-text-1)',
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
      <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--adm-text-3)', letterSpacing: '0.04em' }}>
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
          style={{ flex: 1, background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-1)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.55rem', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer' }}
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
          <p style={{ fontSize: '0.85rem', color: 'var(--adm-text-2)' }}>Uploading and processing…</p>
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
              { label: `Unchanged: ${result.skipped_unchanged}`,bg: '#f8f9fb', color: 'var(--adm-text-2)', border: '#e2e4e9' },
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
                  <li key={i} style={{ fontSize: '0.75rem', color: 'var(--adm-text-2)' }}>
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
// Brand overview helpers
// ---------------------------------------------------------------------------

const BRAND_COLOR: Record<string, string> = {
  'Powerlast':          '#CC0000',
  'Exide Maxx':         '#CC0000',
  'Spark':              '#1d4ed8',
  'SB Flooded':         '#059669',
  'Chloride Exide AGM': '#7e22ce',
  'Exide AGM':          '#6366f1',
  'Supreme':            '#d97706',
  'Sebang':             '#0891b2',
}
function brandColor(brand: string) { return BRAND_COLOR[brand] ?? '#6b7280' }

const BRAND_LOGO: Record<string, string> = {
  'Exide Maxx':         exideMaxLogo,
  'Spark':              sparkLogo,
  'Powerlast':          powerlastLogo,
  'Supreme':            supremeLogo,
  'Sebang':             sebangLogo,
  'Chloride Exide AGM': exideAgmLogo,
  'SB Flooded':         sbFloodedLogo,
}

// Resolve DB brand → display brand.
function resolveDisplayBrand(b: BatteryRow): string {
  const brandUp = (b.brand ?? '').toUpperCase()
  const codeUp  = (b.battery_code ?? '').toUpperCase()
  const techUp  = (b.technology ?? '').toUpperCase()
  if (brandUp.includes('MAXX') || codeUp.includes('MAXX')) return 'Exide Maxx'
  if (brandUp === 'CHLORIDE EXIDE') {
    return techUp === 'AGM' ? 'Chloride Exide AGM' : 'SB Flooded'
  }
  if (brandUp === 'EXIDE MATRIX') {
    return techUp === 'AGM' ? 'Chloride Exide AGM' : 'Exide Matrix'
  }
  return b.brand ?? 'Unknown'
}

function groupByBrand(batteries: BatteryRow[]): Array<{ brand: string; count: number }> {
  const map = new Map<string, number>()
  for (const b of batteries) {
    const key = resolveDisplayBrand(b)
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return Array.from(map.entries())
    .map(([brand, count]) => ({ brand, count }))
    .sort((a, b) => b.count - a.count)
}

const TILE_STYLE: React.CSSProperties = {
  ...CARD,
  padding: '1.4rem 1.5rem 1.1rem',
  display: 'flex',
  flexDirection: 'column',
  gap: '0.85rem',
  minHeight: 220,
  width: 190,
  flex: '0 0 190px',
  transition: 'box-shadow 0.15s, transform 0.1s',
}

function BrandTile({ brand, count, onClick, animDelay = 0 }: { brand: string; count: number; onClick?: () => void; animDelay?: number }) {
  const color = brandColor(brand)
  const logo  = BRAND_LOGO[brand]
  return (
    <div
      onClick={onClick}
      style={{ ...TILE_STYLE, borderTop: `3px solid ${color}`, cursor: 'pointer', animationName: 'admCardIn', animationDuration: '0.4s', animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)', animationFillMode: 'both', animationDelay: `${animDelay}ms` }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 18px rgba(0,0,0,0.13)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.07)'; e.currentTarget.style.transform = 'none' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
          {brand}
        </span>
        <BoltIcon style={{ width: 15, height: 15, color }} />
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {logo ? (
          <img src={logo} alt={brand} style={{ maxHeight: 88, maxWidth: '100%', objectFit: 'contain' }} />
        ) : (
          <span style={{ fontSize: '4rem', fontWeight: 900, color, lineHeight: 1, letterSpacing: '-0.02em' }}>
            {count}
          </span>
        )}
      </div>
      <div style={{ borderTop: '1px solid #e2e4e922', paddingTop: '0.6rem' }}>
        <span style={{ fontSize: '0.68rem', color: 'rgba(107,114,128,0.65)' }}>
          {count} {count === 1 ? 'battery' : 'batteries'}
        </span>
      </div>
    </div>
  )
}

function SearchTile({ onClick, animDelay = 0 }: { onClick: () => void; animDelay?: number }) {
  return (
    <div
      onClick={onClick}
      style={{ ...TILE_STYLE, borderTop: '3px solid #6b7280', cursor: 'pointer', animationName: 'admCardIn', animationDuration: '0.4s', animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)', animationFillMode: 'both', animationDelay: `${animDelay}ms` }}
      onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 4px 18px rgba(0,0,0,0.13)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
      onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.07)'; e.currentTarget.style.transform = 'none' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--adm-text-3)' }}>
          Search
        </span>
        <MagnifyingGlassIcon style={{ width: 15, height: 15, color: '#6b7280' }} />
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <MagnifyingGlassIcon style={{ width: 56, height: 56, color: 'rgba(107,114,128,0.2)' }} />
      </div>
      <div style={{ borderTop: '1px solid #e2e4e922', paddingTop: '0.6rem' }}>
        <span style={{ fontSize: '0.68rem', color: 'rgba(107,114,128,0.65)' }}>Find specific batteries</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AdminBatteries() {
  const [searchParams] = useSearchParams()
  const manage = searchParams.get('manage') === 'true'
  const actionParam = searchParams.get('action')

  // ── View: 'brands' shows the overview; 'brand-detail' shows a brand's list; 'search' shows the table ──
  const [view, setView] = useState<'brands' | 'brand-detail' | 'search'>(manage ? 'search' : 'brands')
  const [selectedBrand, setSelectedBrand] = useState<string | null>(null)

  // ── Overview state ────────────────────────────────────────────────────────
  const [overviewItems, setOverviewItems] = useState<BatteryRow[]>([])
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [total, setTotal] = useState(0)

  // ── Search/table state ────────────────────────────────────────────────────
  const [items, setItems]           = useState<BatteryRow[]>([])
  const [searchTotal, setSearchTotal] = useState(0)
  const [page, setPage]             = useState(1)
  const [search, setSearch]         = useState('')
  const [techFilter, setTech]       = useState('')
  const [loading, setLoading]       = useState(false)
  const [showAdd, setShowAdd]       = useState(false)
  const [editing, setEditing]       = useState<BatteryRow | null>(null)
  const [showUpload, setShowUp]     = useState(false)
  const [deleting, setDeleting]     = useState<number | null>(null)

  const PAGE_SIZE = 50

  // Auto-open Add modal when navigated via the sidebar "Add Battery" sub-link
  useEffect(() => {
    if (actionParam === 'add') setShowAdd(true)
  }, [actionParam])

  // Load all batteries for the brand overview on mount
  useEffect(() => {
    fetchBatteries(1, 1000)
      .then(r => {
        setOverviewItems(r.items)
        setTotal(r.total)
      })
      .finally(() => setOverviewLoading(false))
  }, [])

  async function refreshOverview() {
    const r = await fetchBatteries(1, 1000)
    setOverviewItems(r.items)
    setTotal(r.total)
  }

  // Load paginated search results when in search mode
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetchBatteries(page, PAGE_SIZE, search || undefined, techFilter || undefined)
      setItems(r.items)
      setSearchTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [page, search, techFilter])

  useEffect(() => {
    if (view === 'search') load()
  }, [load, view])

  async function handleAdd(payload: BatteryPayload) {
    await addBattery(payload)
    setShowAdd(false)
    load()
    refreshOverview()
  }

  async function handleUpdate(payload: BatteryPayload) {
    if (!editing) return
    await updateBattery(editing.id, payload)
    setEditing(null)
    load()
    refreshOverview()
  }

  async function handleDelete(id: number) {
    setDeleting(id)
    try {
      await deleteBattery(id)
      load()
      refreshOverview()
    } finally {
      setDeleting(null)
    }
  }

  const totalPages = Math.ceil(searchTotal / PAGE_SIZE)

  // Batteries for the selected brand detail view
  const brandItems = selectedBrand
    ? overviewItems.filter(b => resolveDisplayBrand(b) === selectedBrand)
    : []

  // Group batteries by origin for the brand overview
  const localItems    = overviewItems.filter(b => b.origin?.toLowerCase() === 'local')
  const importedItems = overviewItems.filter(b => b.origin?.toLowerCase() !== 'local')
  const localBrands    = groupByBrand(localItems)
  const importedBrands = groupByBrand(importedItems)

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

  const TABLE_COLS = manage
    ? ['Battery Code', 'Model Key', 'Ah', 'CCA EN', 'Technology', 'Actions']
    : ['Battery Code', 'Model Key', 'Ah', 'CCA EN', 'Technology']

  // ── Shared tab button style ───────────────────────────────────────────────
  function tabStyle(active: boolean): React.CSSProperties {
    return {
      display: 'flex', alignItems: 'center', gap: '0.4rem',
      background: active ? '#fff5f5' : 'transparent',
      color: active ? R : 'var(--adm-text-2)',
      border: active ? `1px solid #f5c6c6` : '1px solid transparent',
      borderRadius: '8px',
      padding: '0.38rem 0.85rem',
      fontSize: '0.78rem',
      fontWeight: 600,
      cursor: 'pointer',
      transition: 'all 0.15s',
    }
  }

  return (
    <AdminLayout>

      {/* ── Header ── */}
      <header style={{ background: 'var(--adm-header-bg)', borderBottom: '1px solid var(--adm-sep)', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <BoltIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Battery Specs</span>
        </div>
        <span style={{ fontSize: '0.72rem', color: 'rgba(107,114,128,0.6)', background: 'var(--adm-subtle-bg)', borderRadius: '99px', padding: '0.2rem 0.7rem', border: '1px solid var(--adm-sep)' }}>
          {total.toLocaleString()} records
        </span>

        {/* Back to overview — shown in search and brand-detail views */}
        {(view === 'search' || view === 'brand-detail') && (
          <div style={{ marginLeft: 'auto' }}>
            <button style={tabStyle(false)} onClick={() => { setView('brands'); setSelectedBrand(null) }}>
              <BoltIcon style={{ width: 13, height: 13 }} />
              ← Overview
            </button>
          </div>
        )}
      </header>

      <main style={{ maxWidth: '1100px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

        {/* ── Brands overview ── */}
        {view === 'brands' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {overviewLoading ? (
              <div style={{ ...CARD, padding: '4rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>
                Loading brands…
              </div>
            ) : (
              <>
                {/* LOCAL section */}
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1rem' }}>
                    <span style={{ background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0', padding: '0.2rem 0.65rem', borderRadius: '99px', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                      Local
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'rgba(107,114,128,0.55)' }}>
                      {localItems.length} batteries · {localBrands.length} brand{localBrands.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.1rem' }}>
                    {localBrands.map((b, i) => <BrandTile key={b.brand} brand={b.brand} count={b.count} animDelay={i * 45} onClick={() => { setSelectedBrand(b.brand); setView('brand-detail') }} />)}
                  </div>
                </div>

                {/* IMPORTED section */}
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1rem' }}>
                    <span style={{ background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', padding: '0.2rem 0.65rem', borderRadius: '99px', fontSize: '0.68rem', fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                      Imported
                    </span>
                    <span style={{ fontSize: '0.7rem', color: 'rgba(107,114,128,0.55)' }}>
                      {importedItems.length} batteries · {importedBrands.length} brand{importedBrands.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.1rem' }}>
                    {importedBrands.map((b, i) => <BrandTile key={b.brand} brand={b.brand} count={b.count} animDelay={200 + i * 45} onClick={() => { setSelectedBrand(b.brand); setView('brand-detail') }} />)}
                    <SearchTile onClick={() => setView('search')} animDelay={200 + importedBrands.length * 45} />
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Brand detail view (read-only) ── */}
        {view === 'brand-detail' && selectedBrand && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div style={{ width: 4, height: 28, borderRadius: 2, background: brandColor(selectedBrand) }} />
              <span style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--adm-text-1)' }}>{selectedBrand}</span>
              <span style={{ fontSize: '0.72rem', color: 'rgba(107,114,128,0.6)', background: 'var(--adm-subtle-bg)', borderRadius: '99px', padding: '0.2rem 0.7rem', border: '1px solid var(--adm-sep)' }}>
                {brandItems.length} {brandItems.length === 1 ? 'battery' : 'batteries'}
              </span>
            </div>
            <div style={{ ...CARD, overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'var(--adm-thead-bg)', borderBottom: '2px solid var(--adm-sep)' }}>
                      {['Battery Code', 'Model Key', 'Ah', 'CCA EN', 'Technology'].map(h => (
                        <th key={h} style={{ padding: '0.8rem 1.1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {overviewLoading && (
                      <tr><td colSpan={5} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>Loading…</td></tr>
                    )}
                    {!overviewLoading && brandItems.length === 0 && (
                      <tr><td colSpan={5} style={{ padding: '3rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.85rem' }}>No batteries found</td></tr>
                    )}
                    {!overviewLoading && brandItems.map((b, i) => (
                      <tr
                        key={b.id}
                        style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none', transition: 'background 0.1s' }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--adm-subtle-bg)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'var(--adm-card-bg)')}
                      >
                        <td style={{ padding: '0.8rem 1.1rem', fontFamily: 'monospace', fontWeight: 700, color: R, fontSize: '0.8rem' }}>{b.battery_code}</td>
                        <td style={{ padding: '0.8rem 1.1rem', fontFamily: 'monospace', fontSize: '0.78rem', color: 'rgba(17,24,39,0.7)' }}>{b.model_key}</td>
                        <td style={{ padding: '0.8rem 1.1rem', fontWeight: 600, color: 'rgba(17,24,39,0.8)' }}>{b.ah}</td>
                        <td style={{ padding: '0.8rem 1.1rem', color: b.cca_en ? 'rgba(17,24,39,0.7)' : 'rgba(107,114,128,0.4)' }}>{b.cca_en ?? '—'}</td>
                        <td style={{ padding: '0.8rem 1.1rem' }}>{techBadge(b.technology)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ── Search / table view ── */}
        {view === 'search' && (
          <>
            {/* Toolbar */}
            <div style={{ ...CARD, padding: '1rem 1.25rem', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'center' }}>
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
                    style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: showUpload ? 'var(--adm-subtle-bg)' : 'var(--adm-card-bg)', color: 'var(--adm-text-1)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.45rem 1rem', fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer' }}
                  >
                    <ArrowUpTrayIcon style={{ width: 14, height: 14 }} /> {showUpload ? 'Hide Upload' : 'Upload .xlsx'}
                  </button>
                  <a
                    href={exportBatteriesUrl()}
                    download
                    style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: 'var(--adm-card-bg)', color: 'var(--adm-text-1)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.45rem 1rem', fontSize: '0.82rem', fontWeight: 600, textDecoration: 'none' }}
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

            {/* Edit modal */}
            {editing && (
              <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: '1rem' }}>
                <div style={{ ...CARD, padding: '1.75rem', width: '100%', maxWidth: '400px', maxHeight: '90vh', overflow: 'auto' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                    <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--adm-text-1)', margin: 0 }}>Edit Battery</h2>
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

            {/* Add Battery modal */}
            {showAdd && (
              <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: '1rem' }}>
                <div style={{ ...CARD, padding: '1.75rem', width: '100%', maxWidth: '400px', maxHeight: '90vh', overflow: 'auto' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
                    <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--adm-text-1)', margin: 0 }}>Add Battery</h2>
                    <button onClick={() => setShowAdd(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: '2px' }}>
                      <XMarkIcon style={{ width: 18, height: 18 }} />
                    </button>
                  </div>
                  <BatteryForm initial={EMPTY_FORM} onSave={handleAdd} onCancel={() => setShowAdd(false)} />
                </div>
              </div>
            )}

            {/* Table */}
            <div style={{ ...CARD, overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'var(--adm-thead-bg)', borderBottom: '2px solid var(--adm-sep)' }}>
                      {TABLE_COLS.map(h => (
                        <th key={h} style={{ padding: '0.8rem 1.1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
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
                        style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none', transition: 'background 0.1s' }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--adm-row-hover)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'var(--adm-card-bg)')}
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
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.78rem', color: 'var(--adm-text-2)' }}>
                <span>{searchTotal.toLocaleString()} total records</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                    style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', fontSize: '0.78rem', fontWeight: 600, cursor: page === 1 ? 'not-allowed' : 'pointer', opacity: page === 1 ? 0.4 : 1 }}
                  >
                    <ChevronLeftIcon style={{ width: 13, height: 13 }} /> Prev
                  </button>
                  <span style={{ padding: '0 0.5rem', fontWeight: 600, color: 'rgba(17,24,39,0.7)' }}>
                    {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', padding: '0.35rem 0.75rem', borderRadius: '7px', border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', fontSize: '0.78rem', fontWeight: 600, cursor: page === totalPages ? 'not-allowed' : 'pointer', opacity: page === totalPages ? 0.4 : 1 }}
                  >
                    Next <ChevronRightIcon style={{ width: 13, height: 13 }} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}

      </main>
    </AdminLayout>
  )
}
