import { useEffect, useState } from 'react'
import { fetchMakes, fetchModels, fetchYears, fetchRecommendation } from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'
import { FeedbackModal } from '@/components/FeedbackModal'
import { AccuracyBar } from '@/components/AccuracyBar'
import { Copy, Check, ChevronLeft } from 'lucide-react'
import ReactCountryFlag from 'react-country-flag'
import { StarIcon, ShoppingBagIcon } from '@heroicons/react/24/outline'
import exideMaxxLogo from '@/assets/exide-max-logo.webp'
import powerlastLogo from '@/assets/powerlast-logo.webp'
import sparkLogo from '@/assets/spark-logo.webp'
import supremeLogo from '@/assets/supreme-logo.webp'
import sebangLogo from '@/assets/sebang-logo.webp'
import sbFloodedLogo from '@/assets/sb-flooded-logo.webp'
import exideAgmLogo from '@/assets/exide-agm-logo.webp'

// ── Helpers (self-contained copies — not exported from VehicleFinderForm) ─────

function getBrandLogo(code: string): string | null {
  const u = code.toUpperCase()
  if (u.includes('MAXX'))          return exideMaxxLogo
  if (u.includes('POWERLAST'))     return powerlastLogo
  if (u.includes('SPARK'))         return sparkLogo
  if (u.includes('SUPREME'))       return supremeLogo
  if (u.includes('SEBANG'))        return sebangLogo
  if (u.includes('CHLORIDE EXIDE'))return sbFloodedLogo
  if (u.includes('EXIDE'))         return exideAgmLogo
  return null
}

function techIconColor(tech?: string): string {
  if (!tech) return '#374151'
  const t = tech.toUpperCase()
  if (t.includes('EFB'))                       return '#c2410c'
  if (t.includes('AGM'))                       return '#5b21b6'
  if (t.includes('SB') || t.includes('FLOOD')) return '#374151'
  return '#374151'
}

function techClass(tech?: string) {
  if (!tech) return 'badge tech-mf'
  const t = tech.toUpperCase()
  if (t.includes('EFB'))                       return 'badge tech-efb'
  if (t.includes('AGM'))                       return 'badge tech-agm'
  if (t.includes('SB') || t.includes('FLOODED')) return 'badge tech-sb'
  return 'badge tech-mf'
}

function CarBatteryIcon({ size = 40, color = '#374151' }: { size?: number; color?: string }) {
  const h = Math.round(size * 0.7)
  return (
    <svg width={size} height={h} viewBox="0 0 48 34" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect x="2" y="9" width="44" height="23" rx="3.5" stroke={color} strokeWidth="2.2" />
      <rect x="2" y="9" width="44" height="8" rx="3.5" fill={color} fillOpacity="0.1" />
      <rect x="8" y="2" width="10" height="9" rx="2" fill={color} />
      <line x1="13" y1="4.5" x2="13" y2="8.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="11" y1="6.5" x2="15" y2="6.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="30" y="2" width="10" height="9" rx="2" fill={color} fillOpacity="0.5" />
      <line x1="32.5" y1="6.5" x2="37.5" y2="6.5" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="18" y1="9" x2="18" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
      <line x1="24" y1="9" x2="24" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
      <line x1="30" y1="9" x2="30" y2="32" stroke={color} strokeWidth="1" strokeOpacity="0.2" />
    </svg>
  )
}

// ── Types ──────────────────────────────────────────────────────────────────────

type Step = 'make' | 'model' | 'year' | 'details' | 'result'

export interface MobileVehicleFinderProps {
  darkMode?: boolean
  onMakesLoaded?: () => void
}

// ── Shared styles ──────────────────────────────────────────────────────────────

const SELECT_STYLE: React.CSSProperties = {
  width: '100%',
  height: '52px',
  padding: '0 0.9rem',
  borderRadius: '0.5rem',
  border: '1.5px solid var(--border, #e2e4e9)',
  background: 'var(--card-bg, #fff)',
  color: 'var(--text, #111827)',
  fontSize: '1rem',
  fontFamily: 'inherit',
  appearance: 'none',
  WebkitAppearance: 'none',
  cursor: 'pointer',
  boxSizing: 'border-box',
}

const BTN_PRIMARY: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem',
  width: '100%', height: '52px',
  background: 'var(--red, #CC0000)', color: '#fff',
  border: 'none', borderRadius: '0.5rem',
  fontSize: '1rem', fontWeight: 700, cursor: 'pointer',
  fontFamily: 'inherit',
}

const BTN_GHOST: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
  width: '100%', height: '52px',
  background: 'transparent', color: 'var(--muted, #6b7280)',
  border: '1.5px solid var(--border, #e2e4e9)', borderRadius: '0.5rem',
  fontSize: '0.95rem', fontWeight: 600, cursor: 'pointer',
  fontFamily: 'inherit',
}

// ── Progress dots ──────────────────────────────────────────────────────────────

function ProgressDots({ current, total = 4 }: { current: number; total?: number }) {
  return (
    <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'center', marginBottom: '1.5rem' }}>
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          style={{
            height: '8px',
            width: i < current ? '20px' : i === current ? '20px' : '8px',
            borderRadius: '999px',
            background: i <= current ? 'var(--red, #CC0000)' : 'var(--border, #e2e4e9)',
            transition: 'all 0.25s ease',
          }}
        />
      ))}
    </div>
  )
}

// ── Select wrapper with custom arrow ──────────────────────────────────────────

function SelectWrap({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ position: 'relative' }}>
      {children}
      <div style={{
        position: 'absolute', right: '0.85rem', top: '50%', transform: 'translateY(-50%)',
        pointerEvents: 'none', color: 'var(--muted, #6b7280)',
      }}>
        <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function MobileVehicleFinder({ onMakesLoaded }: MobileVehicleFinderProps) {
  const [step, setStep] = useState<Step>('make')

  const [makes, setMakes]   = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [years, setYears]   = useState<number[]>([])

  const [make, setMake]         = useState('')
  const [model, setModel]       = useState('')
  const [year, setYear]         = useState('')
  const [fuelType, setFuelType] = useState('')
  const [engineCc, setEngineCc] = useState('')

  const [result, setResult]   = useState<RecommendationResult | null>(null)
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [altVisible, setAltVisible]   = useState(true)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [copied, setCopied]           = useState(false)

  // Load makes on mount
  useEffect(() => {
    fetchMakes()
      .then(data => { setMakes(data); onMakesLoaded?.() })
      .catch(() => setError('Could not load vehicles. Please check your connection.'))
      .finally(() => setLoading(false))
  }, [onMakesLoaded])

  // Auto-advance: make selected → fetch models → go to model step
  const handleMakeChange = async (val: string) => {
    setMake(val)
    setModel(''); setYear(''); setFuelType(''); setEngineCc('')
    setModels([]); setYears([])
    setResult(null); setError('')
    if (!val) return
    setLoading(true)
    try {
      const data = await fetchModels(val)
      setModels(data)
      setStep('model')
    } catch {
      setError('Failed to load models.')
    } finally {
      setLoading(false)
    }
  }

  // Auto-advance: model selected → fetch years → go to year step
  const handleModelChange = async (val: string) => {
    setModel(val)
    setYear(''); setFuelType(''); setEngineCc('')
    setYears([])
    setResult(null); setError('')
    if (!val) return
    setLoading(true)
    try {
      const data = await fetchYears(make, val)
      setYears(data)
      setStep('year')
    } catch {
      setError('Failed to load years.')
    } finally {
      setLoading(false)
    }
  }

  // Year selected → show Continue button (no auto-advance to avoid mis-taps)
  const handleYearChange = (val: string) => {
    setYear(val)
    setResult(null); setError('')
  }

  const handleYearContinue = () => {
    if (year) setStep('details')
  }

  const handleSubmit = async (skipDetails = false) => {
    setSubmitting(true); setError('')
    try {
      const data = await fetchRecommendation({
        make,
        model,
        year:      parseInt(year, 10),
        engine_cc: !skipDetails && engineCc ? parseInt(engineCc, 10) : null,
        fuel_type: !skipDetails && fuelType  ? fuelType  : null,
        stop_start: true,
      })
      setResult(data)
      setStep('result')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBack = () => {
    setError('')
    if (step === 'model')   { setStep('make');    setModel('') }
    if (step === 'year')    { setStep('model');   setYear('') }
    if (step === 'details') { setStep('year');    setFuelType(''); setEngineCc('') }
    if (step === 'result')  { setStep('details'); setResult(null) }
  }

  const handleReset = () => {
    setStep('make')
    setMake(''); setModel(''); setYear(''); setFuelType(''); setEngineCc('')
    setModels([]); setYears([])
    setResult(null); setError('')
    setAltVisible(true)
  }

  const handleCopy = () => {
    if (!result?.primary.battery_code) return
    navigator.clipboard.writeText(result.primary.battery_code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const card: React.CSSProperties = {
    background: 'var(--card-bg, #fff)',
    border: '1px solid var(--border, #e2e4e9)',
    borderRadius: '0.75rem',
    padding: '1.25rem',
    width: '100%',
    boxSizing: 'border-box',
  }

  const stepLabel: React.CSSProperties = {
    fontSize: '0.72rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--red, #CC0000)',
    marginBottom: '0.3rem',
  }

  const stepTitle: React.CSSProperties = {
    fontSize: '1.25rem',
    fontWeight: 800,
    color: 'var(--text, #111827)',
    margin: '0 0 0.25rem',
    lineHeight: 1.2,
  }

  const stepSub: React.CSSProperties = {
    fontSize: '0.82rem',
    color: 'var(--muted, #6b7280)',
    margin: '0 0 1.25rem',
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div style={{ flex: '1 1 0', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

      {/* ── Step: Make ── */}
      {step === 'make' && (
        <div style={card}>
          <ProgressDots current={0} />
          <p style={stepLabel}>Step 1 of 4</p>
          <h2 style={stepTitle}>Select Your Make</h2>
          <p style={stepSub}>Choose the brand of your car</p>

          {loading ? (
            <div style={{ height: 52, borderRadius: '0.5rem', background: 'var(--border, #e2e4e9)', animation: 'pulse 1.5s ease-in-out infinite' }} />
          ) : (
            <SelectWrap>
              <select
                style={SELECT_STYLE}
                value={make}
                onChange={e => handleMakeChange(e.target.value)}
                autoFocus
              >
                <option value="">Choose a make…</option>
                {makes.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </SelectWrap>
          )}

          {error && <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}

          {loading && make && (
            <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: 'var(--muted, #6b7280)' }}>
              Loading models…
            </p>
          )}
        </div>
      )}

      {/* ── Step: Model ── */}
      {step === 'model' && (
        <div style={card}>
          <ProgressDots current={1} />
          <p style={stepLabel}>Step 2 of 4</p>
          <h2 style={stepTitle}>Select Model</h2>
          <p style={stepSub}>{make}</p>

          <SelectWrap>
            <select
              style={SELECT_STYLE}
              value={model}
              onChange={e => handleModelChange(e.target.value)}
              disabled={loading}
              autoFocus
            >
              <option value="">{loading ? 'Loading…' : 'Choose a model…'}</option>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </SelectWrap>

          {error && <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}

          <div style={{ marginTop: '1rem' }}>
            <button style={BTN_GHOST} onClick={handleBack}>
              <ChevronLeft size={18} />
              Back
            </button>
          </div>
        </div>
      )}

      {/* ── Step: Year ── */}
      {step === 'year' && (
        <div style={card}>
          <ProgressDots current={2} />
          <p style={stepLabel}>Step 3 of 4</p>
          <h2 style={stepTitle}>Select Year</h2>
          <p style={stepSub}>{make} {model}</p>

          <SelectWrap>
            <select
              style={SELECT_STYLE}
              value={year}
              onChange={e => handleYearChange(e.target.value)}
              autoFocus
            >
              <option value="">Choose a year…</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </SelectWrap>

          {error && <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '1rem' }}>
            <button
              style={{ ...BTN_PRIMARY, opacity: year ? 1 : 0.45, cursor: year ? 'pointer' : 'not-allowed' }}
              onClick={handleYearContinue}
              disabled={!year}
            >
              Continue
            </button>
            <button style={BTN_GHOST} onClick={handleBack}>
              <ChevronLeft size={18} />
              Back
            </button>
          </div>
        </div>
      )}

      {/* ── Step: Details (optional) ── */}
      {step === 'details' && (
        <div style={card}>
          <ProgressDots current={3} />
          <p style={stepLabel}>Step 4 of 4 — Optional</p>
          <h2 style={stepTitle}>Engine Details</h2>
          <p style={stepSub}>Adding these improves accuracy, but you can skip</p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1rem' }}>
            {/* Fuel type */}
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--muted, #6b7280)', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Fuel Type
              </label>
              <SelectWrap>
                <select
                  style={SELECT_STYLE}
                  value={fuelType}
                  onChange={e => setFuelType(e.target.value)}
                >
                  <option value="">Select fuel type</option>
                  <option value="Petrol">Petrol</option>
                  <option value="Diesel">Diesel</option>
                  <option value="Hybrid">Hybrid</option>
                  <option value="Electric">Electric</option>
                </select>
              </SelectWrap>
            </div>

            {/* Engine CC */}
            <div>
              <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: 'var(--muted, #6b7280)', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Engine Size (CC)
              </label>
              <input
                type="number"
                style={{ ...SELECT_STYLE, paddingRight: '0.9rem' }}
                placeholder="e.g. 1500"
                value={engineCc}
                onChange={e => setEngineCc(e.target.value)}
                min={500}
                max={8000}
              />
              <p style={{ fontSize: '0.72rem', color: 'var(--muted, #9ca3af)', marginTop: '0.3rem' }}>
                Common sizes: 1000, 1300, 1500, 1800, 2000, 2500 cc
              </p>
            </div>
          </div>

          {error && <p style={{ marginBottom: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <button
              style={{ ...BTN_PRIMARY, opacity: submitting ? 0.7 : 1 }}
              onClick={() => handleSubmit(false)}
              disabled={submitting}
            >
              {submitting ? 'Finding battery…' : 'Find My Battery'}
            </button>
            <button
              style={{ ...BTN_GHOST, opacity: submitting ? 0.5 : 1 }}
              onClick={() => handleSubmit(true)}
              disabled={submitting}
            >
              Skip &amp; Find Battery
            </button>
            <button style={BTN_GHOST} onClick={handleBack}>
              <ChevronLeft size={18} />
              Back
            </button>
          </div>
        </div>
      )}

      {/* ── Step: Result ── */}
      {step === 'result' && result && (
        <>
          {/* Result card */}
          <div style={card}>
            {/* Header */}
            <div style={{ marginBottom: '0.85rem' }}>
              <p style={{ ...stepLabel, color: '#16a34a', marginBottom: '0.2rem' }}>Battery Found</p>
              <h2 style={{ ...stepTitle, fontSize: '1.1rem' }}>
                {result.matched_make
                  ? `${result.matched_make} ${result.matched_model} · ${result.matched_year}`
                  : `${result.make} ${result.model} · ${result.year}`}
              </h2>
              {!result.matched_make && (
                <div style={{
                  display: 'flex', alignItems: 'flex-start', gap: '0.4rem',
                  background: '#fffbeb', border: '1px solid #fcd34d',
                  borderRadius: '0.45rem', padding: '0.5rem 0.65rem',
                  marginTop: '0.5rem',
                }}>
                  <span style={{ color: '#d97706', fontSize: '0.85rem', flexShrink: 0 }}>⚠</span>
                  <p style={{ margin: 0, fontSize: '0.72rem', color: '#92400e', lineHeight: 1.5 }}>
                    Exact model not found — estimate based on your {result.engine_cc}cc {result.fuel_type?.toLowerCase()} engine.
                  </p>
                </div>
              )}
            </div>

            {/* Primary battery */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.75rem',
              background: 'var(--bg, #f4f5f7)', borderRadius: '0.6rem',
              padding: '0.85rem 1rem', marginBottom: '0.85rem',
            }}>
              {/* Icon / brand logo */}
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.2rem' }}>
                {getBrandLogo(result.primary.battery_code)
                  ? <img src={getBrandLogo(result.primary.battery_code)!} alt="" style={{ height: 36, width: 'auto', maxWidth: 68, objectFit: 'contain' }} />
                  : <CarBatteryIcon size={38} color={techIconColor(result.primary.technology)} />
                }
                <span style={{ fontSize: '0.62rem', fontWeight: 700, color: techIconColor(result.primary.technology), textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                  {result.primary.technology ?? 'MF'}
                </span>
              </div>

              {/* Specs */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.4rem' }}>
                  <div>
                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text, #111827)', lineHeight: 1 }}>
                      {result.primary.ah ?? '—'}
                    </div>
                    <div style={{ fontSize: '0.68rem', fontWeight: 600, color: 'var(--muted, #6b7280)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Ah
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text, #111827)', lineHeight: 1 }}>
                      {result.primary.cca_en ?? '—'}
                    </div>
                    <div style={{ fontSize: '0.68rem', fontWeight: 600, color: 'var(--muted, #6b7280)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      CCA (EN)
                    </div>
                  </div>
                </div>

                {/* Battery code + copy */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.9rem', fontWeight: 700, color: 'var(--blue, #1A35C0)', letterSpacing: '0.03em' }}>
                    {result.primary.battery_code || '—'}
                  </span>
                  {result.primary.battery_code && (
                    <button
                      onClick={handleCopy}
                      style={{
                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        width: 28, height: 28, borderRadius: 6,
                        border: '1px solid var(--border, #e2e4e9)',
                        background: 'var(--card-bg, #fff)',
                        cursor: 'pointer', color: 'var(--muted, #6b7280)',
                        flexShrink: 0,
                      }}
                      title="Copy battery code"
                    >
                      {copied ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  )}
                </div>

                {result.primary.model_key && (
                  <span style={{ fontSize: '0.68rem', color: 'var(--muted, #9ca3af)', marginTop: '0.2rem', display: 'block' }}>
                    {result.primary.model_key}
                  </span>
                )}
              </div>
            </div>

            {/* Accuracy bar */}
            <div style={{ marginBottom: '0.85rem' }}>
              <AccuracyBar data={result} />
            </div>

            {/* Action buttons */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.85rem' }}>
              <button
                type="button"
                onClick={() => setFeedbackOpen(true)}
                style={{
                  flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
                  height: 44,
                  background: '#fff', border: '1.5px solid var(--red, #CC0000)', color: 'var(--red, #CC0000)',
                  borderRadius: 6, fontSize: '0.82rem', fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                <StarIcon style={{ width: '1rem', height: '1rem' }} />
                Rate
              </button>
              <a
                href="https://www.chlorideexide.com/category/all-products"
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
                  height: 44,
                  background: 'var(--red, #CC0000)', color: '#fff',
                  borderRadius: 6, fontSize: '0.82rem', fontWeight: 700, cursor: 'pointer',
                  fontFamily: 'inherit', textDecoration: 'none',
                }}
              >
                <ShoppingBagIcon style={{ width: '1rem', height: '1rem' }} />
                Shop Now
              </a>
            </div>

            {/* Dial-a-Battery */}
            <div style={{
              display: 'flex', alignItems: 'center', flexWrap: 'wrap',
              gap: '0.3rem 0.75rem',
              background: '#f9fafb', border: '1px solid #e5e7eb',
              borderRadius: 8, padding: '0.45rem 0.75rem',
              fontSize: '0.72rem', marginBottom: '0.85rem',
            }}>
              <span style={{ fontWeight: 700, color: '#374151', whiteSpace: 'nowrap' }}>
                📞 Dial a Battery
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
                <ReactCountryFlag countryCode="KE" svg style={{ width: '1.1em', height: '1.1em' }} />
                <span style={{ color: 'var(--red, #CC0000)', fontWeight: 600 }}>0719 080 000</span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
                <ReactCountryFlag countryCode="TZ" svg style={{ width: '1.1em', height: '1.1em' }} />
                <span style={{ fontWeight: 600 }}>0677 484 631</span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', whiteSpace: 'nowrap' }}>
                <ReactCountryFlag countryCode="UG" svg style={{ width: '1.1em', height: '1.1em' }} />
                <span style={{ color: '#16a34a', fontWeight: 600 }}>0200 400 900</span>
              </span>
            </div>

            {/* Alternatives */}
            {(() => {
              const p = result.primary
              const alts = result.alternatives.filter(a => (a.technology ?? 'MF') === (p.technology ?? 'MF'))
              if (alts.length === 0) return null
              return (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--muted, #6b7280)' }}>
                      Same-Tech Alternatives ({alts.length})
                    </span>
                    <button
                      onClick={() => setAltVisible(v => !v)}
                      style={{ fontSize: '0.72rem', color: 'var(--muted, #6b7280)', background: 'none', border: 'none', cursor: 'pointer', padding: '0.15rem 0.3rem', fontFamily: 'inherit' }}
                    >
                      {altVisible ? 'hide' : 'show'}
                    </button>
                  </div>
                  {altVisible && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
                      {alts.map(alt => (
                        <div key={alt.battery_code} style={{
                          background: 'var(--bg, #f4f5f7)', borderRadius: '0.45rem',
                          padding: '0.5rem 0.6rem', border: '1px solid var(--border, #e2e4e9)',
                        }}>
                          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--text, #111827)', fontFamily: 'monospace', marginBottom: '0.2rem' }}>
                            {alt.battery_code}
                          </div>
                          <div style={{ fontSize: '0.67rem', color: 'var(--muted, #6b7280)' }}>
                            {alt.ah != null ? `${alt.ah} Ah` : ''}
                            {alt.cca_en != null ? ` · ${alt.cca_en} CCA` : ''}
                          </div>
                          <span className={techClass(alt.technology)} style={{ fontSize: '0.62rem', marginTop: '0.3rem', display: 'inline-block' }}>
                            {alt.technology ?? 'MF'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })()}
          </div>

          {/* Search again */}
          <button
            style={{ ...BTN_GHOST, marginBottom: '0.25rem' }}
            onClick={handleReset}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
            Search Again
          </button>
        </>
      )}

      <FeedbackModal
        open={feedbackOpen}
        onClose={() => setFeedbackOpen(false)}
        vehicleLabel={result
          ? result.matched_make
            ? `${result.matched_make} ${result.matched_model} (${result.matched_year})`
            : `${result.make} ${result.model} ${result.year}`
          : `${make} ${model} ${year}`}
        inputType="select"
        matchConfidence={result?.confidence}
        matchType={result?.match_type}
        recommendedBattery={result?.primary?.battery_code ?? undefined}
      />
    </div>
  )
}
