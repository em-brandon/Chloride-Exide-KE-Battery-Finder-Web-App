import { useEffect, useState, useRef } from 'react'
import { fetchMakes, fetchModels, fetchYears, fetchRecommendation } from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'
import { useToast, Toaster } from '@/components/Notification'
import { AccuracyBar } from '@/components/AccuracyBar'
import { FeedbackModal } from '@/components/FeedbackModal'
import { Search, MousePointerClick, Keyboard } from 'lucide-react'
import { ChatBubbleLeftEllipsisIcon } from '@heroicons/react/24/outline'

interface VehicleFinderFormProps {
  onMakesLoaded?: () => void
  onFormReady?: () => void
  typeMode: boolean
  onTypeModeChange: () => void
  onEstConfChange: (conf: { pct: number; label: string; cls: string } | null) => void
  darkMode?: boolean
}

function techClass(tech?: string) {
  if (!tech) return 'badge tech-mf'
  const t = tech.toUpperCase()
  if (t.includes('EFB')) return 'badge tech-efb'
  if (t.includes('AGM')) return 'badge tech-agm'
  if (t.includes('SB') || t.includes('FLOODED')) return 'badge tech-sb'
  return 'badge tech-mf'
}


function techIconColor(tech?: string): string {
  if (!tech) return '#374151'
  const t = tech.toUpperCase()
  if (t.includes('EFB')) return '#c2410c'
  if (t.includes('AGM')) return '#5b21b6'
  if (t.includes('SB') || t.includes('FLOOD')) return '#1d4ed8'
  return '#374151'
}

function CarBatteryIcon({ size = 40, color = '#374151' }: { size?: number; color?: string }) {
  const h = Math.round(size * 0.7)
  return (
    <svg width={size} height={h} viewBox="0 0 48 34" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      {/* Body */}
      <rect x="2" y="9" width="44" height="23" rx="3.5" stroke={color} strokeWidth="2.2" />
      {/* Top highlight strip */}
      <rect x="2" y="9" width="44" height="8" rx="3.5" fill={color} fillOpacity="0.1" />
      {/* + terminal */}
      <rect x="8" y="2" width="10" height="9" rx="2" fill={color} />
      <line x1="13" y1="4.5" x2="13" y2="8.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="11" y1="6.5" x2="15" y2="6.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      {/* − terminal */}
      <rect x="30" y="2" width="10" height="9" rx="2" fill={color} fillOpacity="0.5" />
      <line x1="32.5" y1="6.5" x2="37.5" y2="6.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      {/* Cell dividers */}
      <line x1="18" y1="9" x2="18" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
      <line x1="24" y1="9" x2="24" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
      <line x1="30" y1="9" x2="30" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
    </svg>
  )
}

// ── Result card ───────────────────────────────────────────────────
function ResultPanel({ data, inputType, typedLabel }: { data: RecommendationResult; inputType: string; typedLabel?: string }) {
  const p = data.primary
  const [altVisible, setAltVisible] = useState(true)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const vehicleLabel = inputType === 'type' && typedLabel
    ? typedLabel
    : data.matched_make
      ? `${data.matched_make} ${data.matched_model} (${data.matched_year})`
      : `${data.make} ${data.model} ${data.year}`

  const sameTechAlts = data.alternatives.filter(
    alt => (alt.technology ?? 'MF') === (p.technology ?? 'MF')
  )

  const isFallback = !data.matched_make

  return (
    <div className="result-card">
      <div className="result-header" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.15rem' }}>
        <h2 className="result-title">Battery Recommendation</h2>
        {!isFallback && (
          <p style={{ margin: 0, fontSize: '0.82rem', color: 'var(--muted-foreground, #6b7280)' }}>
            {data.matched_make} {data.matched_model} · {data.matched_year}
          </p>
        )}
      </div>

      {isFallback && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
          background: '#fffbeb', border: '1px solid #fcd34d',
          borderRadius: '0.5rem', padding: '0.5rem 0.75rem', marginBottom: '0.25rem',
        }}>
          <span style={{ color: '#d97706', fontSize: '0.85rem', lineHeight: 1.4, flexShrink: 0, marginTop: '0.05rem' }}>⚠</span>
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#92400e', lineHeight: 1.5 }}>
            Your exact model wasn't found in our records. This is an estimate based on your{' '}
            {data.engine_cc}cc {data.fuel_type?.toLowerCase()} engine — confirm with a mechanic before purchasing.
          </p>
        </div>
      )}

      <div className="primary-card">
        <div className="primary-battery-icon">
          <CarBatteryIcon size={42} color={techIconColor(p.technology)} />
          <div className="primary-battery-icon-label" style={{ color: techIconColor(p.technology) }}>
            {p.technology ?? 'MF'}
          </div>
        </div>
        <div className="primary-spec">
          <div className="value">{p.ah ?? '—'}</div>
          <div className="unit">Ah</div>
        </div>
        <div className="primary-spec">
          <div className="value">{p.cca_en ?? '—'}</div>
          <div className="unit">CCA (EN)</div>
        </div>
        <div className="primary-name">
          <div className="battery-code">{p.battery_code || '—'}</div>
          {p.model_key && <div className="model-key">{p.model_key}</div>}
        </div>
      </div>

      <AccuracyBar data={data} />

      {sameTechAlts.length > 0 && (
        <div style={{ marginTop: '0.5rem' }}>
          <div className="alt-header">
            <span>Same-Technology Alternatives ({sameTechAlts.length})</span>
            <button className="alt-toggle-btn" onClick={() => setAltVisible(v => !v)}>
              {altVisible ? 'hide' : 'show'}
            </button>
          </div>
          {altVisible && (
            <div className={`alt-grid ${sameTechAlts.length > 5 ? 'alt-grid--condensed' : ''}`}>
              {sameTechAlts.map(alt => (
                <div key={alt.battery_code} className="alt-card">
                  <div className="ac-card-header">
                    <CarBatteryIcon size={15} color={techIconColor(alt.technology)} />
                    <div className="ac-code">{alt.battery_code}</div>
                  </div>
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

      {/* Feedback trigger */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.75rem' }}>
        <button
          type="button"
          onClick={() => setFeedbackOpen(true)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.375rem',
            background: 'none', border: '1px solid var(--border, #d1d5db)',
            borderRadius: '0.5rem', padding: '0.375rem 0.75rem',
            fontSize: '0.75rem', fontWeight: 500, cursor: 'pointer',
            color: 'var(--muted-foreground, #6b7280)',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--foreground, #111827)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--muted-foreground, #6b7280)')}
        >
          <ChatBubbleLeftEllipsisIcon style={{ width: '1rem', height: '1rem' }} />
          Rate this result
        </button>
      </div>

      <FeedbackModal
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        vehicleLabel={vehicleLabel}
        inputType={inputType}
        matchConfidence={data.confidence}
        matchType={data.match_type}
        recommendedBattery={data.primary?.battery_code ?? undefined}
      />
    </div>
  )
}

// ── Main form ─────────────────────────────────────────────────────
export function VehicleFinderForm({ onMakesLoaded, onFormReady, typeMode, onTypeModeChange, onEstConfChange }: VehicleFinderFormProps) {
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

  // i-stop toggle
  const [istop, setIstop] = useState(true)
  const [istopTooltip, setIstopTooltip] = useState(false)
  const istopTooltipRef = useRef<HTMLDivElement>(null)

  // UI state
  const [submitted, setSubmitted] = useState(false)
  const [loadingMakes, setLoadingMakes]   = useState(true)
  const [loadingModels, setLoadingModels] = useState(false)
  const [loadingYears, setLoadingYears]   = useState(false)
  const [submitting, setSubmitting]       = useState(false)
  const [, setFormReady]         = useState(false)

  // Close i-stop tooltip on outside click
  useEffect(() => {
    if (!istopTooltip) return
    function handleClick(e: MouseEvent) {
      if (istopTooltipRef.current && !istopTooltipRef.current.contains(e.target as Node)) {
        setIstopTooltip(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [istopTooltip])

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
    onTypeModeChange()
    setMake(''); setModel(''); setYear('')
    setMakeText(''); setModelText(''); setYearText('')
    setModels([]); setYears([])
    setResult(null); setErrorMsg('')
    setSubmitted(false)
  }

  // Reset all fields
  const handleReset = () => {
    setMake(''); setModel(''); setYear('')
    setMakeText(''); setModelText(''); setYearText('')
    setFuelType(''); setEngineCc('')
    setModels([]); setYears([])
    setResult(null); setErrorMsg('')
    setSubmitted(false)
    setIstop(true)
  }

  // Estimated confidence — 0 until make has input, hides after submit until all cleared
  const estimatedConf = (() => {
    if (!typeMode) return null
    // Hide after submit; reappear only when all text fields are empty again
    const anyFilled = makeText.trim() || modelText.trim() || yearText.trim() || engineCc || fuelType
    if (submitted && anyFilled) return null
    if (!makeText.trim()) return { pct: 0, label: 'Enter your vehicle make to begin', cls: 'bar-fill low', step: 0 }
    const hasModel = !!modelText.trim()
    const hasYear  = !!yearText.trim()
    const hasFuel  = !!fuelType
    const hasCC    = !!engineCc
    if (hasModel && hasYear && hasFuel && hasCC) return { pct: 85, label: 'High — all details provided', cls: 'bar-fill high', step: 4 }
    if (hasModel && hasYear) return { pct: 70, label: 'Good — add fuel type & engine size to improve', cls: 'bar-fill medium', step: 3 }
    if (hasModel) return { pct: 55, label: 'Fair — add year, fuel type & engine size', cls: 'bar-fill medium', step: 2 }
    return { pct: 40, label: 'Low — only make entered', cls: 'bar-fill low', step: 1 }
  })()

  // Report conf changes to parent (for nav badge)
  useEffect(() => {
    onEstConfChange(estimatedConf)
  }, [typeMode, makeText, modelText, yearText, engineCc, fuelType, submitted])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)
    setErrorMsg('')

    // Validation in type mode
    if (typeMode) {
      const y = parseInt(yearText, 10)
      if (!yearText.trim() || isNaN(y) || y < 1960 || y > 2030) {
        pushToast('error', 'Invalid year', 'Please enter a valid year between 1960 and 2030.')
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
        make:       typeMode ? makeText.trim()  : make,
        model:      typeMode ? modelText.trim() : model,
        year:       typeMode ? parseInt(yearText, 10) : parseInt(year, 10),
        fuel_type:  fuelType || null,
        engine_cc:  engineCc ? parseInt(engineCc, 10) : null,
        stop_start: istop,
      })
      setResult(data)
      setSubmitted(true)
      pushToast('success', 'Battery found!')
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

  const sideBySize = !!result

  return (
    <div className="finder-wrapper">
      <Toaster items={toasts} onDismiss={dismissToast} />

      <div className={`finder-layout${sideBySize ? ' has-result' : ''}`}>
      {/* Form column */}
      <div className="finder-card">
      <form onSubmit={handleSubmit} noValidate>
        <div className="form-card-heading">
          <p className="form-tagline">Enter your vehicle details to get the right battery recommendation</p>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {result && (
              <button type="button" className="btn-mode" onClick={handleReset}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="lucide lucide-eraser-icon lucide-eraser"
                  style={{ marginRight: '5px', flexShrink: 0 }}
                  aria-hidden="true"
                  focusable="false"
                >
                  <path d="M21 21H8a2 2 0 0 1-1.42-.587l-3.994-3.999a2 2 0 0 1 0-2.828l10-10a2 2 0 0 1 2.829 0l5.999 6a2 2 0 0 1 0 2.828L12.834 21" />
                  <path d="m5.082 11.09 8.828 8.828" />
                </svg>
                Reset
              </button>
            )}
            <button
              type="button"
              className={`btn-mode${typeMode ? ' active' : ''}`}
              onClick={handleModeToggle}
              aria-pressed={typeMode}
            >
              {typeMode ? (
                <><Keyboard size={15} strokeWidth={1.75} style={{ marginRight: '5px' }} />Type</>
              ) : (
                <><MousePointerClick size={15} strokeWidth={2.0} style={{ marginRight: '5px' }} />Select</>
              )}
            </button>
          </div>
        </div>

        <div className="form-grid">
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
            {!typeMode && make && (
              <p className="model-missing-hint">
                Don't see your model?{' '}
                <button type="button" className="model-missing-hint-btn" onClick={handleModeToggle}>
                  Type your query instead →
                </button>
              </p>
            )}
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

        {/* i-stop toggle */}
        <div className="form-group full" style={{ marginTop: '0.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }} ref={istopTooltipRef}>
              <span className="form-label" style={{ marginBottom: 0 }}>Is car i-stop enabled?</span>
              <div style={{ position: 'relative' }}>
                <button
                  type="button"
                  className="conf-info-btn"
                  onClick={() => setIstopTooltip(v => !v)}
                  aria-label="What is i-stop?"
                >?</button>
                {istopTooltip && (
                  <div className="conf-popover istop-popover" style={{ width: '270px' }}>
                    <strong>What is i-stop?</strong>
                    <p style={{ marginTop: '0.35rem' }}>i-stop (Idle Stop System) automatically shuts off the engine when the car is stationary — e.g. at traffic lights — to save fuel. You will notice the engine restarting when you release the brake.</p>
                    <p style={{ marginTop: '0.4rem' }}>Cars with i-stop require an <strong>EFB</strong> or <strong>AGM</strong> battery to handle the extra charge cycles. Standard MF batteries wear out quickly in these vehicles.</p>
                    <p style={{ marginTop: '0.4rem', color: 'var(--muted)' }}>Turn this <strong>OFF</strong> if your car does not have an automatic start-stop system.</p>
                  </div>
                )}
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={istop}
              onClick={() => setIstop(v => !v)}
              style={{
                position: 'relative',
                width: '2.75rem',
                height: '1.5rem',
                borderRadius: '9999px',
                border: 'none',
                cursor: 'pointer',
                background: istop ? 'var(--red, #CC0000)' : '#d1d5db',
                transition: 'background 0.2s',
                flexShrink: 0,
                padding: 0,
              }}
            >
              <span style={{
                position: 'absolute',
                top: '2px',
                left: istop ? 'calc(100% - 22px)' : '2px',
                width: '20px',
                height: '20px',
                borderRadius: '50%',
                background: '#fff',
                boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
                transition: 'left 0.2s',
                display: 'block',
              }} />
            </button>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--muted)', marginTop: '0.3rem' }}>
            {istop
              ? 'ON — will recommend EFB or AGM battery'
              : 'OFF — will recommend standard MF battery'}
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
      </div>

      {/* Result column on the right */}
      {result && (
        <div className="result-side-card">
          <ResultPanel
            data={result}
            inputType={typeMode ? 'type' : 'select'}
            typedLabel={typeMode ? `${makeText.trim()} ${modelText.trim()} ${yearText.trim()}`.trim() : undefined}
          />
        </div>
      )}
      </div> {/* end finder-layout */}
    </div>
  )
}
