import { useEffect, useState, useCallback } from 'react'
import { fetchMakes, fetchModels, fetchYears, fetchRecommendation } from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'
import { SkeletonForm } from '@/components/SkeletonForm'
import { ResultCard } from '@/components/ResultCard'
import { CheckCircle2, Search } from 'lucide-react'
import { cn } from '@/lib/utils'

interface VehicleFinderFormProps {
  onMakesLoaded?: () => void
}

type SubmitState = 'idle' | 'loading' | 'success' | 'error'

export function VehicleFinderForm({ onMakesLoaded }: VehicleFinderFormProps) {
  // Data state
  const [makes, setMakes]   = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [years, setYears]   = useState<number[]>([])
  const [result, setResult] = useState<RecommendationResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')

  // Form state
  const [make, setMake]   = useState('')
  const [model, setModel] = useState('')
  const [year, setYear]   = useState('')

  // UI state
  const [loadingMakes, setLoadingMakes] = useState(true)
  const [loadingModels, setLoadingModels] = useState(false)
  const [loadingYears, setLoadingYears]   = useState(false)
  const [submitState, setSubmitState]     = useState<SubmitState>('idle')

  // Revealed steps (progressive reveal)
  const [modelVisible, setModelVisible] = useState(false)
  const [yearVisible, setYearVisible]   = useState(false)
  const [resultVisible, setResultVisible] = useState(false)

  // Load makes on mount
  useEffect(() => {
    fetchMakes()
      .then(data => { setMakes(data); onMakesLoaded?.() })
      .catch(() => setErrorMsg('Could not load vehicle makes. Is the backend running?'))
      .finally(() => setLoadingMakes(false))
  }, [onMakesLoaded])

  // Load models when make changes
  const handleMakeChange = useCallback(async (val: string) => {
    setMake(val)
    setModel('')
    setYear('')
    setModels([])
    setYears([])
    setModelVisible(false)
    setYearVisible(false)
    setResult(null)
    setResultVisible(false)
    if (!val) return
    setLoadingModels(true)
    try {
      const data = await fetchModels(val)
      setModels(data)
      setModelVisible(true)
    } finally {
      setLoadingModels(false)
    }
  }, [])

  // Load years when model changes
  const handleModelChange = useCallback(async (val: string) => {
    setModel(val)
    setYear('')
    setYears([])
    setYearVisible(false)
    setResult(null)
    setResultVisible(false)
    if (!val || !make) return
    setLoadingYears(true)
    try {
      const data = await fetchYears(make, val)
      setYears(data)
      setYearVisible(true)
    } finally {
      setLoadingYears(false)
    }
  }, [make])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!make || !model || !year) return
    setSubmitState('loading')
    setErrorMsg('')
    setResult(null)
    setResultVisible(false)
    try {
      const data = await fetchRecommendation({
        make, model,
        year: parseInt(year, 10),
        engine_cc: null,
        fuel_type: null,
      })
      setSubmitState('success')
      setResult(data)
      setTimeout(() => {
        setSubmitState('idle')
        setResultVisible(true)
      }, 800)
    } catch (err) {
      setSubmitState('error')
      setErrorMsg(err instanceof Error ? err.message : 'Recommendation failed.')
      setTimeout(() => setSubmitState('idle'), 1500)
    }
  }

  if (loadingMakes) return <SkeletonForm />

  return (
    <div>
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Make */}
        <Field label="Make">
          <select
            className={selectCls}
            value={make}
            onChange={e => handleMakeChange(e.target.value)}
            disabled={loadingMakes}
          >
            <option value="">Select make…</option>
            {makes.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </Field>

        {/* Model — progressive reveal */}
        {modelVisible && (
          <div className="animate-slide-up">
            <Field label="Model">
              {loadingModels ? (
                <div className={cn(selectCls, 'flex items-center text-muted-foreground text-sm')}>
                  Loading models…
                </div>
              ) : (
                <select
                  className={selectCls}
                  value={model}
                  onChange={e => handleModelChange(e.target.value)}
                >
                  <option value="">Select model…</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              )}
            </Field>
          </div>
        )}

        {/* Year — progressive reveal */}
        {yearVisible && (
          <div className="animate-slide-up">
            <Field label="Year">
              {loadingYears ? (
                <div className={cn(selectCls, 'flex items-center text-muted-foreground text-sm')}>
                  Loading years…
                </div>
              ) : (
                <select
                  className={selectCls}
                  value={year}
                  onChange={e => setYear(e.target.value)}
                >
                  <option value="">Select year…</option>
                  {years.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              )}
            </Field>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!make || !model || !year || submitState === 'loading'}
          className={cn(
            'w-full h-10 rounded-md font-semibold text-sm transition-all duration-300 flex items-center justify-center gap-2',
            submitState === 'success'
              ? 'bg-emerald-500 text-white animate-success-pop'
              : submitState === 'error'
              ? 'bg-red-400 text-white'
              : 'bg-[#cc0000] hover:bg-[#b30000] text-white disabled:opacity-40 disabled:cursor-not-allowed'
          )}
        >
          {submitState === 'success' ? (
            <><CheckCircle2 size={16} /> Found!</>
          ) : submitState === 'loading' ? (
            <span className="animate-spin border-2 border-white/40 border-t-white rounded-full w-4 h-4" />
          ) : (
            <><Search size={15} /> Find Battery</>
          )}
        </button>

        {errorMsg && (
          <p className="text-sm text-red-500 text-center">{errorMsg}</p>
        )}
      </form>

      {/* Result */}
      {result && resultVisible && <ResultCard data={result} />}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  )
}

const selectCls =
  'w-full rounded-md border border-input bg-background px-3 h-10 text-sm text-foreground ' +
  'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 ' +
  'dark:bg-card dark:border-border'
