import { useEffect, useState, useRef } from 'react'
import { fetchMakes, fetchModels, fetchYears, fetchRecommendation } from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'
import { useToast, Toaster } from '@/components/Notification'
import { Search } from 'lucide-react'

interface VehicleFinderFormProps {
  onMakesLoaded?: () => void
  onFormReady?: () => void
}

function techClass(tech?: string) {
  if (!tech) return 'badge tech-mf'
  const t = tech.toUpperCase()
  if (t.includes('EFB')) return 'badge tech-efb'
  if (t.includes('AGM')) return 'badge tech-agm'
  if (t.includes('SB') || t.includes('FLOODED')) return 'badge tech-sb'
  return 'badge tech-mf'
}

function matchClass(matchType: string) {
  const m = matchType.toLowerCase()
  if (m.includes('exact')) return 'badge exact'
  if (m.includes('close')) return 'badge close'
  return 'badge fallback'
}

// ── Result card ───────────────────────────────────────────────────
function ResultPanel({ data }: { data: RecommendationResult }) {
  const p = data.primary
  const [altVisible, setAltVisible] = useState(true)
  const barRef = useRef<HTMLDivElement>(null)

  // Animate confidence bar on mount
  useEffect(() => {
    if (!barRef.current) return
    barRef.current.style.width = '0%'
    const t = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (barRef.current) barRef.current.style.width = `${data.confidence}%`
      })
    })
    return () => cancelAnimationFrame(t)
  }, [data.confidence])

  const barClass = data.confidence === 100 ? 'bar-fill high' : data.confidence >= 60 ? 'bar-fill medium' : 'bar-fill low'

  return (
    <div className="result-card">
      <div className="result-header">
        <h2 className="result-title">Primary Recommendation</h2>
        <span className={matchClass(data.match_type)}>{data.match_type}</span>
      </div>

      <div className="primary-card">
        <div className="primary-spec">
          <div className="value">{p.ah ?? '—'}</div>
          <div className="unit">Ah</div>
        </div>
        <div className="primary-spec">
          <div className="value">{p.cca_en ?? '—'}</div>
          <div className="unit">CCA (EN)</div>
        </div>
        <span className={techClass(p.technology)} style={{ fontSize: '0.72rem' }}>
          {p.technology ?? 'MF'}
        </span>
        <div className="primary-name">
          <div className="battery-code">{p.battery_code || '—'}</div>
          {p.model_key && <div className="model-key">{p.model_key}</div>}
        </div>
      </div>

      <div className="confidence-section">
        <div className="conf-row">
          <span>Match Confidence</span>
          <span>{data.confidence}%</span>
        </div>
        <div className="bar-track">
          <div ref={barRef} className={barClass} style={{ width: '0%' }} />
        </div>
      </div>

      <div className="matched-info">
        {data.matched_make
          ? `Matched to: ${data.matched_make} ${data.matched_model} (${data.matched_year})`
          : 'No model match found — result based on engine size and fuel type only'}
      </div>

      {data.alternatives.length > 0 && (
        <div style={{ marginTop: '1.25rem' }}>
          <div className="alt-header">
            <span>Alternative Options ({data.alternatives.length})</span>
            <button className="alt-toggle-btn" onClick={() => setAltVisible(v => !v)}>
              {altVisible ? 'hide' : 'show'}
            </button>
          </div>
          {altVisible && (
            <div className="alt-grid">
              {data.alternatives.map(alt => (
                <div key={alt.battery_code} className="alt-card">
                  <div className="ac-code">{alt.battery_code}</div>
                  <div className="ac-specs">
                    {alt.ah != null ? `${alt.ah} Ah` : ''}
                    {alt.cca_en != null ? ` · ${alt.cca_en} CCA` : ''}
                  </div>
                  <span className={techClass(alt.technology)} style={{ fontSize: '0.68rem', marginTop: '0.35rem', display: 'inline-block' }}>
                    {alt.technology ?? 'MF'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main form ─────────────────────────────────────────────────────
export function VehicleFinderForm({ onMakesLoaded, onFormReady }: VehicleFinderFormProps) {
  const { toasts, push: pushToast, dismiss: dismissToast } = useToast()

  // Data
  const [makes, setMakes]   = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [years, setYears]   = useState<number[]>([])
  const [result, setResult] = useState<RecommendationResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // Form values
  const [make, setMake]   = useState('')
  const [model, setModel] = useState('')
  const [year, setYear]   = useState('')
  const [fuelType, setFuelType]   = useState('')
  const [engineCc, setEngineCc]   = useState('')

  // Text-mode values
  const [makeText, setMakeText]   = useState('')
  const [modelText, setModelText] = useState('')
  const [yearText, setYearText]   = useState('')

  // UI state
  const [typeMode, setTypeMode] = useState(false)
  const [loadingMakes, setLoadingMakes]   = useState(true)
  const [loadingModels, setLoadingModels] = useState(false)
  const [loadingYears, setLoadingYears]   = useState(false)
  const [submitting, setSubmitting]       = useState(false)
  const [, setFormReady]         = useState(false)

  // Load makes on mount
  useEffect(() => {
    fetchMakes()
      .then(data => {
        setMakes(data)
        setFormReady(true)
        onMakesLoaded?.()
        onFormReady?.()
      })
      .catch(() => {
        setErrorMsg('Could not load vehicle makes. Is the backend running?')
        setFormReady(true)
        onMakesLoaded?.()
        onFormReady?.()
      })
      .finally(() => setLoadingMakes(false))
  }, [onMakesLoaded, onFormReady])

  // Load models when make changes (select mode)
  const handleMakeChange = async (val: string) => {
    setMake(val)
    setModel('')
    setYear('')
    setModels([])
    setYears([])
    setResult(null)
    setErrorMsg('')
    if (!val) return
    setLoadingModels(true)
    try {
      const data = await fetchModels(val)
      setModels(data)
    } catch {
      pushToast('error', 'Failed to load models', 'Check that the backend is running.')
    } finally {
      setLoadingModels(false)
    }
  }

  // Load years when model changes (select mode)
  const handleModelChange = async (val: string) => {
    setModel(val)
    setYear('')
    setYears([])
    setResult(null)
    setErrorMsg('')
    if (!val || !make) return
    setLoadingYears(true)
    try {
      const data = await fetchYears(make, val)
      setYears(data)
    } catch {
      pushToast('error', 'Failed to load years', 'Check that the backend is running.')
    } finally {
      setLoadingYears(false)
    }
  }

  // Toggle type mode
  const handleModeToggle = () => {
    setTypeMode(t => !t)
    setMake(''); setModel(''); setYear('')
    setMakeText(''); setModelText(''); setYearText('')
    setModels([]); setYears([])
    setResult(null); setErrorMsg('')
  }

  // Estimated confidence preview in type mode
  const estimatedConf = (() => {
    if (!typeMode) return null
    const hasAll = makeText.trim() && modelText.trim() && yearText.trim()
    const hasFull = hasAll && engineCc && fuelType
    if (hasFull) return { pct: 85, label: 'High probability match — complete manual input', cls: 'bar-fill high' }
    if (hasAll)  return { pct: 70, label: 'Close match likely — typed make/model/year improves search', cls: 'bar-fill medium' }
    return { pct: 40, label: 'Rule-based match — engine size and fuel carry more weight', cls: 'bar-fill low' }
  })()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    setErrorMsg('')

    // Validation in type mode
    if (typeMode) {
      const y = parseInt(yearText, 10)
      if (!yearText.trim() || isNaN(y) || y < 1990 || y > 2030) {
        pushToast('error', 'Invalid year', 'Please enter a valid year between 1990 and 2030.')
        return
      }
      if (!engineCc) {
        pushToast('error', 'Engine size required', 'Engine CC is required when entering vehicle details manually.')
        return
      }
      if (!fuelType) {
        pushToast('error', 'Fuel type required', 'Fuel Type is required when entering vehicle details manually.')
        return
      }
    }

    setSubmitting(true)
    try {
      const data = await fetchRecommendation({
        make:      typeMode ? makeText.trim()  : make,
        model:     typeMode ? modelText.trim() : model,
        year:      typeMode ? parseInt(yearText, 10) : parseInt(year, 10),
        fuel_type: fuelType || null,
        engine_cc: engineCc ? parseInt(engineCc, 10) : null,
      })
      setResult(data)
      pushToast(
        'success',
        'Battery found!',
        `${data.primary.battery_code} — ${data.primary.ah} Ah · ${data.confidence}% confidence`
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Something went wrong.'
      setErrorMsg(msg)
      pushToast('error', 'Recommendation failed', msg)
    } finally {
      setSubmitting(false)
    }
  }

  // Can submit?
  const canSubmit = typeMode
    ? !!makeText.trim() && !!modelText.trim() && !!yearText.trim()
    : !!make && !!model && !!year

  const sideBySize = !!result && !typeMode

  return (
    <div className={`finder-layout${sideBySize ? ' has-result' : ''}`}>
      <Toaster items={toasts} onDismiss={dismissToast} />

      {/* Form column */}
      <div className="finder-card">
      <form onSubmit={handleSubmit} noValidate>
        {/* Manual mode banner */}
        {typeMode && (
          <div className="manual-banner">
            <span className="badge close" style={{ fontSize: '0.7rem', alignSelf: 'flex-start' }}>
              Manual Mode Active
            </span>
            <span>You are entering vehicle details manually. Matching will rely more on engine size and fuel type.</span>
          </div>
        )}

        {/* Confidence preview in type mode */}
        {typeMode && estimatedConf && (
          <div style={{ marginBottom: '1rem', padding: '0.85rem 1rem', background: '#f9fafb', border: '1px solid #e2e4e9', borderRadius: '0.5rem' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
              Estimated Match Confidence
            </div>
            <div className="bar-track" style={{ marginBottom: '0.45rem' }}>
              <div className={estimatedConf.cls} style={{ width: `${estimatedConf.pct}%` }} />
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
              {estimatedConf.pct}% — {estimatedConf.label}
            </div>
          </div>
        )}

        <div className="form-grid">
          {/* Mode toggle row */}
          <div className="form-group full">
            <label className="form-label">Make / Model / Year Input</label>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                className={`btn-mode${typeMode ? ' active' : ''}`}
                onClick={handleModeToggle}
                aria-pressed={typeMode}
              >
                {typeMode ? 'Select' : 'Type'}
              </button>
            </div>
          </div>

          {/* Make */}
          <div className="form-group">
            <label className="form-label" htmlFor="make-select">Car Make</label>
            <div className="form-input-wrap">
              <select
                id="make-select"
                className="form-select"
                style={{ display: typeMode ? 'none' : 'block', flex: 1 }}
                value={make}
                onChange={e => handleMakeChange(e.target.value)}
                disabled={typeMode || loadingMakes}
              >
                <option value="">{loadingMakes ? 'Loading…' : 'Select make'}</option>
                {makes.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <input
                type="text"
                className="form-input"
                style={{ display: typeMode ? 'block' : 'none', flex: 1 }}
                placeholder="e.g. Toyota"
                value={makeText}
                onChange={e => setMakeText(e.target.value)}
                autoComplete="off"
                disabled={!typeMode}
              />
            </div>
          </div>

          {/* Model */}
          <div className="form-group">
            <label className="form-label" htmlFor="model-select">Model</label>
            <div className="form-input-wrap">
              <select
                id="model-select"
                className="form-select"
                style={{ display: typeMode ? 'none' : 'block', flex: 1 }}
                value={model}
                onChange={e => handleModelChange(e.target.value)}
                disabled={typeMode || !make || loadingModels}
              >
                <option value="">
                  {loadingModels ? 'Loading…' : make ? 'Select model' : 'Select make first'}
                </option>
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <input
                type="text"
                className="form-input"
                style={{ display: typeMode ? 'block' : 'none', flex: 1 }}
                placeholder="e.g. Corolla"
                value={modelText}
                onChange={e => setModelText(e.target.value)}
                autoComplete="off"
                disabled={!typeMode}
              />
            </div>
          </div>

          {/* Year */}
          <div className="form-group">
            <label className="form-label" htmlFor="year-select">Year</label>
            <div className="form-input-wrap">
              <select
                id="year-select"
                className="form-select"
                style={{ display: typeMode ? 'none' : 'block', flex: 1 }}
                value={year}
                onChange={e => setYear(e.target.value)}
                disabled={typeMode || !model || loadingYears}
              >
                <option value="">
                  {loadingYears ? 'Loading…' : model ? 'Select year' : 'Select model first'}
                </option>
                {years.map(y => <option key={y} value={y}>{y}</option>)}
              </select>
              <input
                type="number"
                className="form-input"
                style={{ display: typeMode ? 'block' : 'none', flex: 1 }}
                placeholder="e.g. 2019"
                value={yearText}
                onChange={e => setYearText(e.target.value)}
                min={1990} max={2030}
                disabled={!typeMode}
              />
            </div>
          </div>

          {/* Fuel type */}
          <div className="form-group">
            <label className="form-label" htmlFor="fuel-select">
              Fuel Type{' '}
              {!typeMode && <span className="optional">(optional)</span>}
            </label>
            <select
              id="fuel-select"
              className="form-select"
              value={fuelType}
              onChange={e => setFuelType(e.target.value)}
            >
              <option value="">Select fuel type</option>
              <option value="Petrol">Petrol</option>
              <option value="Diesel">Diesel</option>
              <option value="Hybrid">Hybrid</option>
              <option value="Electric">Electric</option>
            </select>
            {typeMode && !fuelType && (
              <div className="required-hint" style={{ display: 'block' }}>
                Required in manual mode
              </div>
            )}
          </div>

          {/* Engine CC */}
          <div className="form-group full">
            <label className="form-label" htmlFor="engine-cc">
              Engine Size (CC){' '}
              {!typeMode && <span className="optional">(optional)</span>}
            </label>
            <input
              id="engine-cc"
              type="number"
              className="form-input"
              placeholder="e.g. 1500"
              value={engineCc}
              onChange={e => setEngineCc(e.target.value)}
              min={500} max={8000}
            />
            {typeMode && !engineCc && (
              <div className="required-hint" style={{ display: 'block' }}>
                Required in manual mode
              </div>
            )}
            <div className="hint-box">
              Check your registration document or dashboard sticker — common sizes: 1000, 1300, 1500, 1800, 2000, 2500, 3000 cc.
            </div>
          </div>
        </div>

        <button
          type="submit"
          className="btn-submit"
          disabled={!canSubmit || submitting}
        >
          {submitting
            ? <><span className="spinner" /> Finding…</>
            : <><Search size={15} /> Find Battery</>}
        </button>

        {errorMsg && (
          <div className="error-block">{errorMsg}</div>
        )}
      </form>

      {/* In type mode: result below form */}
      {result && typeMode && <ResultPanel data={result} />}
      </div>

      {/* In select mode: result on the right */}
      {result && !typeMode && (
        <div className="result-side-card">
          <ResultPanel data={result} />
        </div>
      )}
    </div>
  )
}
