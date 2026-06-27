import { useEffect, useRef, useState } from 'react'
import { fetchMakes, fetchModels, fetchYears, fetchRecommendation } from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'
import { FeedbackModal } from '@/components/FeedbackModal'
import { AccuracyBar } from '@/components/AccuracyBar'
import { Clipboard, ClipboardCheck, ChevronLeft, Keyboard, MousePointerClick } from 'lucide-react'
import ReactCountryFlag from 'react-country-flag'
import { StarIcon, ShoppingBagIcon } from '@heroicons/react/24/outline'
import exideMaxxLogo from '@/assets/exide-max-logo.webp'
import powerlastLogo from '@/assets/powerlast-logo.webp'
import sparkLogo from '@/assets/spark-logo.webp'
import supremeLogo from '@/assets/supreme-logo.webp'
import sebangLogo from '@/assets/sebang-logo.webp'
import sbFloodedLogo from '@/assets/sb-flooded-logo.webp'
import exideAgmLogo from '@/assets/exide-agm-logo.webp'

// ── Helpers ────────────────────────────────────────────────────────────────────

function getBrandLogo(code: string): string | null {
  const u = code.toUpperCase()
  if (u.includes('MAXX'))           return exideMaxxLogo
  if (u.includes('POWERLAST'))      return powerlastLogo
  if (u.includes('SPARK'))          return sparkLogo
  if (u.includes('SUPREME'))        return supremeLogo
  if (u.includes('SEBANG'))         return sebangLogo
  if (u.includes('CHLORIDE EXIDE')) return sbFloodedLogo
  if (u.includes('EXIDE'))          return exideAgmLogo
  return null
}

function techIconColor(tech?: string): string {
  if (!tech) return '#374151'
  const t = tech.toUpperCase()
  if (t.includes('EFB'))                        return '#c2410c'
  if (t.includes('AGM'))                        return '#5b21b6'
  if (t.includes('SB') || t.includes('FLOOD'))  return '#374151'
  return '#374151'
}

function techClass(tech?: string) {
  if (!tech) return 'badge tech-mf'
  const t = tech.toUpperCase()
  if (t.includes('EFB'))                          return 'badge tech-efb'
  if (t.includes('AGM'))                          return 'badge tech-agm'
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

const INPUT_STYLE: React.CSSProperties = {
  width: '100%',
  height: '52px',
  padding: '0 0.9rem',
  borderRadius: '0.5rem',
  border: '1.5px solid var(--border, #e2e4e9)',
  background: 'var(--card-bg, #fff)',
  color: 'var(--text, #111827)',
  fontSize: '1rem',
  fontFamily: 'inherit',
  boxSizing: 'border-box',
}

const SELECT_STYLE: React.CSSProperties = {
  ...INPUT_STYLE,
  appearance: 'none',
  WebkitAppearance: 'none',
  cursor: 'pointer',
  paddingRight: '2.2rem',
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

const DIVIDER: React.CSSProperties = {
  borderTop: '1px solid var(--border, #e5e7eb)',
  margin: '0.5rem 0',
}

// ── Step progress strip ────────────────────────────────────────────────────────

const STEP_PCT: Record<string, number> = { make: 25, model: 50, year: 75, details: 100 }

function StepStrip({ step }: { step: string }) {
  const pct = STEP_PCT[step] ?? 100
  return (
    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '3px', background: 'var(--border, #e5e7eb)' }}>
      <div style={{
        height: '100%',
        width: `${pct}%`,
        background: 'var(--red, #CC0000)',
        transition: 'width 0.4s ease',
      }} />
    </div>
  )
}

// ── Progress dots ──────────────────────────────────────────────────────────────

function ProgressDots({ current, total = 4 }: { current: number; total?: number }) {
  return (
    <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'center', marginBottom: '1.25rem' }}>
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          style={{
            height: '6px',
            width: i <= current ? '22px' : '6px',
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

// ── Shimmer skeleton card ──────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div style={{
      background: 'var(--card-bg, #fff)',
      border: '1px solid var(--border, #e2e4e9)',
      borderRadius: '0.75rem',
      padding: '1.5rem 1.25rem',
    }}>
      <div className="skeleton-line" style={{ height: 6, width: '35%', marginBottom: '1.75rem' }} />
      <div className="skeleton-line" style={{ height: 11, width: '28%', marginBottom: '0.5rem' }} />
      <div className="skeleton-line" style={{ height: 22, width: '65%', marginBottom: '0.35rem' }} />
      <div className="skeleton-line" style={{ height: 11, width: '45%', marginBottom: '1.5rem' }} />
      <div className="skeleton-line" style={{ height: 52, width: '100%', borderRadius: '0.5rem' }} />
    </div>
  )
}

// ── Mode toggle pill ──────────────────────────────────────────────────────────

function ModeToggle({ typeMode, onToggle }: { typeMode: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      style={{
        position: 'absolute', top: '1rem', right: '1rem',
        display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
        padding: '0.25rem 0.6rem',
        borderRadius: '999px',
        border: '1px solid var(--border, #e2e4e9)',
        background: 'var(--bg, #f4f5f7)',
        color: 'var(--muted, #6b7280)',
        fontSize: '0.7rem', fontWeight: 700, cursor: 'pointer',
        fontFamily: 'inherit', letterSpacing: '0.03em',
        textTransform: 'uppercase',
      }}
      title={typeMode ? 'Switch to dropdown mode' : 'Switch to manual text input'}
    >
      {typeMode
        ? <><MousePointerClick size={11} />Dropdowns</>
        : <><Keyboard size={11} />Type</>}
    </button>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function MobileVehicleFinder({ darkMode = false, onMakesLoaded }: MobileVehicleFinderProps) {
  const [step, setStep] = useState<Step>('make')
  const [typeMode, setTypeMode] = useState(false)

  const [makes, setMakes]   = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [years, setYears]   = useState<number[]>([])

  const [make, setMake]         = useState('')
  const [model, setModel]       = useState('')
  const [year, setYear]         = useState('')
  const [fuelType, setFuelType] = useState('')
  const [engineCc, setEngineCc] = useState('')

  const [result, setResult]         = useState<RecommendationResult | null>(null)
  const [error, setError]           = useState('')
  const [loading, setLoading]       = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [stopStart, setStopStart]               = useState(true)
  const [stopStartTooltip, setStopStartTooltip] = useState(false)

  const [altVisible, setAltVisible]     = useState(true)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [copied, setCopied]             = useState(false)

  const [toastVisible, setToastVisible] = useState(false)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = () => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToastVisible(true)
    toastTimer.current = setTimeout(() => setToastVisible(false), 4000)
  }

  const handleSwitchToDropdown = () => {
    setTypeMode(false)
    setModel(''); setYear('')
    setYears([])
    setToastVisible(false)
    if (toastTimer.current) clearTimeout(toastTimer.current)
  }

  // Load makes on mount
  useEffect(() => {
    fetchMakes()
      .then(data => { setMakes(data); onMakesLoaded?.() })
      .catch(() => setError('Could not load vehicles. Please check your connection.'))
      .finally(() => setLoading(false))
  }, [onMakesLoaded])

  const handleTypeModeToggle = () => {
    setTypeMode(t => !t)
    setMake(''); setModel(''); setYear('')
    setModels([]); setYears([])
    setResult(null); setError('')
  }

  const handleTypeModelInstead = () => {
    setTypeMode(true)
    setModel(''); setYear('')
    setYears([])
    setResult(null); setError('')
    // make is intentionally preserved
    showToast()
  }

  // ── Select-mode handlers (auto-advance) ──────────────────────────

  const handleMakeSelect = async (val: string) => {
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

  const handleModelSelect = async (val: string) => {
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

  // ── Type-mode continue handlers ───────────────────────────────────

  const handleMakeContinue = () => {
    if (!make.trim()) return
    setError('')
    setStep('model')
  }

  const handleModelContinue = () => {
    if (!model.trim()) return
    setError('')
    setStep('year')
  }

  const handleYearContinue = () => {
    const y = parseInt(year, 10)
    if (typeMode && (isNaN(y) || y < 1960 || y > 2030)) {
      setError('Please enter a valid year between 1960 and 2030.')
      return
    }
    if (year) { setError(''); setStep('details') }
  }

  const handleSubmit = async (skipDetails = false) => {
    setSubmitting(true); setError('')
    try {
      const data = await fetchRecommendation({
        make,
        model,
        year:       parseInt(year, 10),
        engine_cc:  !skipDetails && engineCc ? parseInt(engineCc, 10) : null,
        fuel_type:  !skipDetails && fuelType  ? fuelType  : null,
        stop_start: stopStart,
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
    setStopStart(true); setStopStartTooltip(false)
    setAltVisible(true)
  }

  const handleCopy = () => {
    if (!result?.primary.battery_code) return
    navigator.clipboard.writeText(result.primary.battery_code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  // ── Shared card + typography styles ──────────────────────────────

  const card: React.CSSProperties = {
    position: 'relative',
    background: 'var(--card-bg, #fff)',
    border: '1px solid var(--border, #e2e4e9)',
    borderRadius: '0.75rem',
    padding: '1rem 1rem 0.9rem',
    width: '100%',
    boxSizing: 'border-box',
    overflow: 'hidden',
  }

  const stepChip: React.CSSProperties = {
    display: 'inline-block',
    fontSize: '0.68rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.07em',
    color: 'var(--red, #CC0000)',
    marginBottom: '0.3rem',
  }

  const stepTitle: React.CSSProperties = {
    fontSize: '1.3rem',
    fontWeight: 800,
    color: 'var(--text, #111827)',
    margin: '0 0 0.2rem',
    lineHeight: 1.2,
    paddingRight: '4rem',
  }

  const stepSub: React.CSSProperties = {
    fontSize: '0.82rem',
    color: 'var(--muted, #6b7280)',
    margin: '0 0 1.1rem',
  }

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: '0.72rem',
    fontWeight: 700,
    color: 'var(--muted, #6b7280)',
    marginBottom: '0.35rem',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  }

  // ── Warning banner colours (amber — needs darkMode prop) ──────────

  const warningBg     = darkMode ? 'rgba(253,224,71,0.08)' : '#fffbeb'
  const warningBorder = darkMode ? 'rgba(253,224,71,0.22)' : '#fcd34d'
  const warningText   = darkMode ? '#fbbf24'               : '#92400e'

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div style={{ flex: '1 1 0', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.75rem', maxWidth: '480px', marginLeft: 'auto', marginRight: 'auto', width: '100%' }}>

      {/* ── Step: Make ── */}
      {step === 'make' && (
        loading ? <SkeletonCard /> : (
          <div style={card}>
            <StepStrip step="make" />
            <ModeToggle typeMode={typeMode} onToggle={handleTypeModeToggle} />
            <ProgressDots current={0} />
            <p style={stepChip}>Step 1 of 4</p>
            <h2 style={stepTitle}>Select Your Make</h2>
            <p style={stepSub}>Choose the brand of your vehicle</p>

            {typeMode ? (
              <>
                <input
                  style={INPUT_STYLE}
                  type="text"
                  placeholder="e.g. Toyota"
                  value={make}
                  onChange={e => setMake(e.target.value)}
                  autoFocus
                />
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '1rem' }}>
                  <button
                    style={{ ...BTN_PRIMARY, opacity: make.trim() ? 1 : 0.45, cursor: make.trim() ? 'pointer' : 'not-allowed' }}
                    onClick={handleMakeContinue}
                    disabled={!make.trim()}
                  >
                    Continue
                  </button>
                </div>
              </>
            ) : (
              <SelectWrap>
                <select
                  style={SELECT_STYLE}
                  value={make}
                  onChange={e => handleMakeSelect(e.target.value)}
                  autoFocus
                >
                  <option value="">Choose a make…</option>
                  {makes.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </SelectWrap>
            )}

            {error && <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}
          </div>
        )
      )}

      {/* ── Step: Model ── */}
      {step === 'model' && (
        <div style={card}>
          <StepStrip step="model" />
          <ModeToggle typeMode={typeMode} onToggle={handleTypeModeToggle} />
          <ProgressDots current={1} />

          {typeMode && toastVisible && (
            <div
              onClick={handleSwitchToDropdown}
              style={{
                background: '#1f2937', color: '#fff',
                borderRadius: '0.6rem', padding: '0.65rem 0.85rem',
                marginBottom: '0.75rem', cursor: 'pointer',
                display: 'flex', flexDirection: 'column', gap: '0.1rem',
              }}
            >
              <span style={{ fontSize: '0.72rem', opacity: 0.75 }}>Switched to manual entry</span>
              <span style={{ fontSize: '0.82rem', fontWeight: 700 }}>Tap here to use dropdown instead →</span>
            </div>
          )}

          <p style={stepChip}>Step 2 of 4</p>
          <h2 style={stepTitle}>Select Model</h2>
          <p style={stepSub}>{make}</p>

          {typeMode ? (
            <input
              style={INPUT_STYLE}
              type="text"
              placeholder="e.g. Corolla"
              value={model}
              onChange={e => setModel(e.target.value)}
              autoFocus
            />
          ) : (
            <>
              <SelectWrap>
                <select
                  style={SELECT_STYLE}
                  value={model}
                  onChange={e => handleModelSelect(e.target.value)}
                  disabled={loading}
                  autoFocus
                >
                  <option value="">{loading ? 'Loading…' : 'Choose a model…'}</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </SelectWrap>
              <button
                onClick={handleTypeModelInstead}
                style={{
                  background: 'none', border: 'none', padding: '0.55rem 0 0',
                  fontSize: '0.8rem', fontWeight: 600,
                  color: 'var(--blue, #2563eb)',
                  cursor: 'pointer', fontFamily: 'inherit',
                  textDecoration: 'underline', textUnderlineOffset: '3px',
                  textAlign: 'left',
                }}
              >
                Don't see your model? Type it instead →
              </button>
            </>
          )}

          {error && <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: '#dc2626' }}>{error}</p>}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '1rem' }}>
            {typeMode && (
              <button
                style={{ ...BTN_PRIMARY, opacity: model.trim() ? 1 : 0.45, cursor: model.trim() ? 'pointer' : 'not-allowed' }}
                onClick={handleModelContinue}
                disabled={!model.trim()}
              >
                Continue
              </button>
            )}
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
          <StepStrip step="year" />
          <ModeToggle typeMode={typeMode} onToggle={handleTypeModeToggle} />
          <ProgressDots current={2} />
          <p style={stepChip}>Step 3 of 4</p>
          <h2 style={stepTitle}>Select Year</h2>
          <p style={stepSub}>{make} {model}</p>

          {typeMode ? (
            <input
              style={INPUT_STYLE}
              type="number"
              placeholder="e.g. 2019"
              value={year}
              onChange={e => setYear(e.target.value)}
              min={1960}
              max={2030}
              autoFocus
            />
          ) : (
            <SelectWrap>
              <select
                style={SELECT_STYLE}
                value={year}
                onChange={e => { setYear(e.target.value); setError('') }}
                autoFocus
              >
                <option value="">Choose a year…</option>
                {years.map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </SelectWrap>
          )}

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
          <StepStrip step="details" />
          <ProgressDots current={3} />
          <p style={stepChip}>Step 4 of 4 — Optional</p>
          <h2 style={{ ...stepTitle, paddingRight: 0 }}>Engine Details</h2>
          <p style={stepSub}>Adding these improves accuracy, but you can skip</p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginBottom: '1.1rem' }}>
            <div>
              <label style={labelStyle}>Fuel Type</label>
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

            {/* ── Start-Stop toggle ── */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <span style={labelStyle}>Start-Stop system?</span>
                  <button
                    type="button"
                    onClick={() => setStopStartTooltip(v => !v)}
                    style={{
                      width: 16, height: 16, borderRadius: '50%',
                      border: '1.5px solid var(--border, #e2e4e9)',
                      background: 'transparent', color: 'var(--muted, #6b7280)',
                      fontSize: '0.62rem', fontWeight: 700, cursor: 'pointer',
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: 'inherit', flexShrink: 0, lineHeight: 1, marginBottom: '0.35rem',
                    }}
                    aria-label="What is Start-Stop?"
                  >?</button>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={stopStart}
                  onClick={() => setStopStart(v => !v)}
                  style={{
                    position: 'relative', width: '2.5rem', height: '1.35rem',
                    borderRadius: '9999px', border: 'none', cursor: 'pointer',
                    background: stopStart ? 'var(--red, #CC0000)' : '#d1d5db',
                    transition: 'background 0.2s', padding: 0, flexShrink: 0,
                  }}
                >
                  <span style={{
                    position: 'absolute', top: '2px',
                    left: stopStart ? 'calc(100% - 19px)' : '2px',
                    width: '17px', height: '17px', borderRadius: '50%',
                    background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
                    transition: 'left 0.2s', display: 'block',
                  }} />
                </button>
              </div>
              {stopStartTooltip && (
                <div style={{
                  background: 'var(--card-bg, #fff)',
                  border: '1px solid var(--border, #e2e4e9)',
                  borderRadius: '0.5rem', padding: '0.6rem 0.75rem',
                  fontSize: '0.72rem', color: 'var(--text, #374151)',
                  lineHeight: 1.5, marginBottom: '0.35rem',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
                }}>
                  <strong>What is Start-Stop?</strong>
                  <p style={{ margin: '0.25rem 0 0' }}>
                    Start-Stop (ISS) shuts off the engine at standstill to save fuel and restarts when you release the brake.
                    Vehicles with this system require an <strong>EFB</strong> or <strong>AGM</strong> battery — standard MF batteries wear out quickly.
                  </p>
                </div>
              )}
              <p style={{ fontSize: '0.7rem', color: 'var(--muted, #9ca3af)', margin: '0.15rem 0 0' }}>
                {stopStart ? 'ON — will recommend EFB or AGM' : 'OFF — will recommend standard MF'}
              </p>
            </div>

            <div>
              <label style={labelStyle}>Engine Size (CC)</label>
              <input
                type="number"
                style={INPUT_STYLE}
                placeholder="e.g. 1500"
                value={engineCc}
                onChange={e => setEngineCc(e.target.value)}
                min={500}
                max={8000}
              />
              <p style={{ fontSize: '0.7rem', color: 'var(--muted, #9ca3af)', marginTop: '0.3rem' }}>
                Common: 1000 · 1300 · 1500 · 1800 · 2000 · 2500 cc
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
              style={{ ...BTN_GHOST, opacity: submitting ? 0.5 : 1, color: 'var(--blue, #1A35C0)', borderColor: 'var(--blue, #1A35C0)' }}
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
      {step === 'result' && result && (() => {
        const p = result.primary
        const logo = getBrandLogo(p.battery_code)
        const iconColor = techIconColor(p.technology)
        const alts = result.alternatives.filter(a => (a.technology ?? 'MF') === (p.technology ?? 'MF'))

        return (
          <>
            <div style={card}>

              {/* ── Vehicle header ── */}
              <div style={{ marginBottom: '1rem' }}>
                <p style={{ ...stepChip, color: '#16a34a' }}>Battery Found</p>
                <h2 style={{ ...stepTitle, fontSize: '1.05rem', paddingRight: 0, marginBottom: '0.5rem' }}>
                  {result.matched_make
                    ? `${result.matched_make} ${result.matched_model} · ${result.matched_year}`
                    : `${result.make} ${result.model} · ${result.year}`}
                </h2>
                {!result.matched_make && (
                  <div style={{
                    display: 'flex', alignItems: 'flex-start', gap: '0.4rem',
                    background: warningBg, border: `1px solid ${warningBorder}`,
                    borderRadius: '0.45rem', padding: '0.55rem 0.7rem',
                  }}>
                    <span style={{ color: warningText, fontSize: '0.85rem', flexShrink: 0 }}>⚠</span>
                    <p style={{ margin: 0, fontSize: '0.72rem', color: warningText, lineHeight: 1.5 }}>
                      Exact model not found — estimate based on your {result.engine_cc}cc {result.fuel_type?.toLowerCase()} engine.
                    </p>
                  </div>
                )}
              </div>

              <div style={DIVIDER} />

              {/* ── Brand logo / icon — centered ── */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem', padding: '0.25rem 0 0.5rem' }}>
                {logo
                  ? <img src={logo} alt="" style={{ height: 52, width: 'auto', maxWidth: 100, objectFit: 'contain' }} />
                  : <CarBatteryIcon size={52} color={iconColor} />
                }
                <span className={techClass(p.technology)} style={{ fontSize: '0.68rem' }}>
                  {p.technology ?? 'MF'}
                </span>
              </div>

              {/* ── Battery code — above stats, full width ── */}
              <div style={{
                background: 'var(--bg, #f4f5f7)',
                borderRadius: '0.5rem',
                padding: '0.65rem 0.85rem',
                marginBottom: '0.5rem',
                border: '1px solid var(--border, #e2e4e9)',
              }}>
                <div style={{
                  fontFamily: 'monospace', fontSize: '1.05rem', fontWeight: 700,
                  color: 'var(--blue, #1A35C0)', letterSpacing: '0.03em',
                  overflowWrap: 'break-word',
                  marginBottom: p.battery_code ? '0.5rem' : 0,
                }}>
                  {p.battery_code || '—'}
                </div>
                {p.battery_code && (
                  <button
                    onClick={handleCopy}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                      padding: '0.28rem 0.65rem',
                      borderRadius: '0.4rem',
                      border: '1px solid var(--border, #e2e4e9)',
                      background: 'var(--card-bg, #fff)',
                      cursor: 'pointer',
                      color: copied ? '#16a34a' : 'var(--muted, #6b7280)',
                      fontSize: '0.72rem', fontWeight: 600,
                      fontFamily: 'inherit',
                      transition: 'color 0.2s',
                    }}
                  >
                    {copied ? <ClipboardCheck size={13} /> : <Clipboard size={13} />}
                    {copied ? 'Copied!' : 'Copy code'}
                  </button>
                )}
              </div>

              {/* ── Stats grid — Ah + CCA ── */}
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr',
                gap: '0.5rem', marginBottom: '0.6rem',
              }}>
                {[
                  { value: p.ah,     unit: 'Ah',       label: 'Capacity' },
                  { value: p.cca_en, unit: 'CCA (EN)', label: 'Cold Crank' },
                ].map(({ value, unit, label }) => (
                  <div key={unit} style={{
                    background: 'var(--bg, #f4f5f7)',
                    borderRadius: '0.5rem',
                    padding: '0.7rem 0.85rem',
                    border: '1px solid var(--border, #e2e4e9)',
                  }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text, #111827)', lineHeight: 1 }}>
                      {value ?? '—'}
                    </div>
                    <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--red, #CC0000)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: '0.2rem' }}>
                      {unit}
                    </div>
                    <div style={{ fontSize: '0.65rem', color: 'var(--muted, #9ca3af)', marginTop: '0.1rem' }}>
                      {label}
                    </div>
                  </div>
                ))}
              </div>
              {p.model_key && (
                <p style={{ fontSize: '0.68rem', color: 'var(--muted, #9ca3af)', margin: '0 0 0.5rem 0.1rem' }}>
                  {p.model_key}
                </p>
              )}

              <div style={DIVIDER} />

              {/* ── Accuracy bar — own row, no overlap ── */}
              <div style={{ padding: '0.1rem 0 0.25rem' }}>
                <AccuracyBar data={result} compact />
              </div>

              <div style={DIVIDER} />

              {/* ── Action buttons ── */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', padding: '0.1rem 0' }}>
                <button
                  type="button"
                  onClick={() => setFeedbackOpen(true)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
                    height: 46,
                    background: 'var(--card-bg, #fff)',
                    border: '1.5px solid var(--red, #CC0000)',
                    color: 'var(--red, #CC0000)',
                    borderRadius: 8, fontSize: '0.85rem', fontWeight: 700,
                    cursor: 'pointer', fontFamily: 'inherit',
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
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
                    height: 46,
                    background: 'var(--red, #CC0000)', color: '#fff',
                    borderRadius: 8, fontSize: '0.85rem', fontWeight: 700,
                    cursor: 'pointer', fontFamily: 'inherit', textDecoration: 'none',
                  }}
                >
                  <ShoppingBagIcon style={{ width: '1rem', height: '1rem' }} />
                  Shop Now
                </a>
              </div>

              <div style={DIVIDER} />

              {/* ── Dial-a-Battery — vertical list with phone animation ── */}
              <div style={{
                background: 'var(--bg, #f4f5f7)',
                border: '1px solid var(--border, #e5e7eb)',
                borderRadius: 10, padding: '0.75rem 1rem',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.6rem' }}>
                  <span className="dial-ring" style={{ display: 'inline-block', fontSize: '1.05rem', lineHeight: 1 }}>📞</span>
                  <span style={{ fontWeight: 700, fontSize: '0.8rem', color: 'var(--text, #374151)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Dial a Battery
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                  {[
                    { code: 'KE', num: '+254 719 080 000', color: 'var(--red, #CC0000)' },
                    { code: 'TZ', num: '+255 677 484 631', color: 'var(--text, #374151)' },
                    { code: 'UG', num: '+256 200 400 900', color: '#16a34a' },
                  ].map(({ code, num, color }) => (
                    <div key={code} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <ReactCountryFlag countryCode={code} svg style={{ width: '1.15em', height: '1.15em', flexShrink: 0 }} />
                      <span style={{ fontSize: '0.82rem', fontWeight: 600, color }}>
                        {num}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* ── Alternatives — single column ── */}
              {alts.length > 0 && (
                <>
                  <div style={DIVIDER} />
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
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
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                        {alts.map(alt => (
                          <div key={alt.battery_code} style={{
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            background: 'var(--bg, #f4f5f7)', borderRadius: '0.5rem',
                            padding: '0.55rem 0.75rem', border: '1px solid var(--border, #e2e4e9)',
                          }}>
                            <div>
                              <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text, #111827)', fontFamily: 'monospace' }}>
                                {alt.battery_code}
                              </div>
                              <div style={{ fontSize: '0.68rem', color: 'var(--muted, #6b7280)', marginTop: '0.1rem' }}>
                                {alt.ah != null ? `${alt.ah} Ah` : ''}
                                {alt.cca_en != null ? ` · ${alt.cca_en} CCA` : ''}
                              </div>
                            </div>
                            <span className={techClass(alt.technology)} style={{ fontSize: '0.62rem', flexShrink: 0 }}>
                              {alt.technology ?? 'MF'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* ── Search again ── */}
            <button style={{ ...BTN_GHOST, marginBottom: '0.25rem' }} onClick={handleReset}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              Search Again
            </button>
          </>
        )
      })()}

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
