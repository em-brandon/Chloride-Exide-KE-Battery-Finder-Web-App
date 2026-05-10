/**
 * FeedbackModal.tsx
 *
 * Left-side slide-in feedback panel styled with the app's CSS variable system.
 * Submits are logged to console only — no backend required.
 */

import { useState, useEffect } from 'react'
import {
  StarIcon,
  XMarkIcon,
  CheckCircleIcon,
} from '@heroicons/react/24/outline'
import { StarIcon as StarSolid } from '@heroicons/react/24/solid'

// ── Types ────────────────────────────────────────────────────────────────────

type Accuracy = 'exact' | 'close' | 'wrong' | 'unsure' | ''

interface WrongPart {
  voltage_ah: boolean
  cca: boolean
  battery_type: boolean
  part_number: boolean
  other: boolean
}

interface FeedbackPayload {
  satisfaction: number          // 1-5 stars
  accuracy: Accuracy
  wrong_parts: WrongPart
  comments: string
  submitted_at: string
}

interface FeedbackModalProps {
  open: boolean
  onClose: () => void
  vehicleLabel: string          // e.g. "Toyota Camry 2020"
}

// ── Constants ────────────────────────────────────────────────────────────────

const ACCURACY_OPTIONS: { value: Accuracy; label: string }[] = [
  { value: 'exact',  label: 'Exact match — correct battery' },
  { value: 'close',  label: 'Close but not quite right' },
  { value: 'wrong',  label: 'Wrong battery recommended' },
  { value: 'unsure', label: 'Not sure' },
]

const WRONG_PART_LABELS: { key: keyof WrongPart; label: string }[] = [
  { key: 'voltage_ah',   label: 'Voltage / Ah capacity' },
  { key: 'cca',          label: 'Cold Cranking Amps (CCA)' },
  { key: 'battery_type', label: 'Battery type (AGM / EFB / MF)' },
  { key: 'part_number',  label: 'Part / battery code' },
  { key: 'other',        label: 'Other' },
]

const MAX_CHARS = 400

// ── Sub-components ───────────────────────────────────────────────────────────

function StarRating({
  value,
  onChange,
}: {
  value: number
  onChange: (n: number) => void
}) {
  const [hover, setHover] = useState(0)

  return (
    <div className="fb-star-row" role="radiogroup" aria-label="Overall satisfaction">
      {[1, 2, 3, 4, 5].map(n => {
        const filled = n <= (hover || value)
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n > 1 ? 's' : ''}`}
            onClick={() => onChange(n)}
            onMouseEnter={() => setHover(n)}
            onMouseLeave={() => setHover(0)}
            className="fb-star-btn"
          >
            {filled ? (
              <StarSolid style={{ width: '1.5rem', height: '1.5rem', color: '#f59e0b' }} />
            ) : (
              <StarIcon style={{ width: '1.5rem', height: '1.5rem', color: 'var(--muted2)' }} />
            )}
          </button>
        )
      })}
    </div>
  )
}

// ── Success screen ───────────────────────────────────────────────────────────

function SuccessScreen({ onClose }: { onClose: () => void }) {
  return (
    <div className="fb-success">
      <CheckCircleIcon style={{ width: '2.75rem', height: '2.75rem', color: '#34d399' }} />
      <h3 className="fb-success-title">Thanks for your feedback!</h3>
      <p className="fb-success-body">Your response has been recorded. It helps us improve battery matching accuracy.</p>
      <button type="button" onClick={onClose} className="btn-submit" style={{ marginTop: '0.5rem', width: 'auto', padding: '0.5rem 1.5rem', fontSize: '0.9rem' }}>
        Close
      </button>
    </div>
  )
}

// ── Main modal ───────────────────────────────────────────────────────────────

const BLANK_WRONG: WrongPart = {
  voltage_ah:   false,
  cca:          false,
  battery_type: false,
  part_number:  false,
  other:        false,
}

export function FeedbackModal({ open, onClose, vehicleLabel }: FeedbackModalProps) {
  const [satisfaction, setSatisfaction] = useState(0)
  const [accuracy, setAccuracy]         = useState<Accuracy>('')
  const [wrongParts, setWrongParts]     = useState<WrongPart>(BLANK_WRONG)
  const [comments, setComments]         = useState('')
  const [submitted, setSubmitted]       = useState(false)
  const [error, setError]               = useState('')

  // Reset state when panel reopens
  useEffect(() => {
    if (open) {
      setSatisfaction(0)
      setAccuracy('')
      setWrongParts(BLANK_WRONG)
      setComments('')
      setSubmitted(false)
      setError('')
    }
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  function toggleWrongPart(key: keyof WrongPart) {
    setWrongParts(prev => ({ ...prev, [key]: !prev[key] }))
  }

  function handleSubmit() {
    if (satisfaction === 0) {
      setError('Please select a star rating before submitting.')
      return
    }
    const payload: FeedbackPayload = {
      satisfaction,
      accuracy,
      wrong_parts: wrongParts,
      comments: comments.trim(),
      submitted_at: new Date().toISOString(),
    }
    // No backend — log only. Safe to replace with a real fetch() later.
    console.log('[Feedback]', vehicleLabel, payload)
    setSubmitted(true)
  }

  const commentQ = (accuracy === 'close' || accuracy === 'wrong') ? '4.' : '3.'

  return (
    <div className={`fb-drawer${open ? ' fb-drawer--open' : ''}`} role="dialog" aria-modal="true" aria-labelledby="fb-title">
      {/* Header */}
      <div className="fb-header">
        <h2 id="fb-title" className="fb-header-title">Rate this result</h2>
        <button type="button" onClick={onClose} aria-label="Close feedback panel" className="fb-close-btn">
          <XMarkIcon style={{ width: '1.1rem', height: '1.1rem' }} />
        </button>
      </div>

      {submitted ? (
        <SuccessScreen onClose={onClose} />
      ) : (
        <div className="fb-body">
          <p className="fb-vehicle-label">
            Feedback for: <strong>{vehicleLabel}</strong>
          </p>

          {/* Q1 — Star rating */}
          <fieldset className="fb-fieldset">
            <legend className="form-label" style={{ marginBottom: '0.5rem' }}>
              1. How satisfied are you with this recommendation?
            </legend>
            <StarRating value={satisfaction} onChange={setSatisfaction} />
            {satisfaction > 0 && (
              <p className="fb-star-label">
                {['', 'Very dissatisfied', 'Dissatisfied', 'Neutral', 'Satisfied', 'Very satisfied'][satisfaction]}
              </p>
            )}
          </fieldset>

          {/* Q2 — Accuracy */}
          <fieldset className="fb-fieldset">
            <legend className="form-label" style={{ marginBottom: '0.5rem' }}>
              2. How accurate was the battery recommendation?
            </legend>
            <div className="fb-options">
              {ACCURACY_OPTIONS.map(opt => (
                <label
                  key={opt.value}
                  className={`fb-option${accuracy === opt.value ? ' fb-option--selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="accuracy"
                    value={opt.value}
                    checked={accuracy === opt.value}
                    onChange={() => setAccuracy(opt.value)}
                    style={{ accentColor: 'var(--red)' }}
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </fieldset>

          {/* Q3 — Which part wrong (conditional) */}
          {(accuracy === 'close' || accuracy === 'wrong') && (
            <fieldset className="fb-fieldset">
              <legend className="form-label" style={{ marginBottom: '0.5rem' }}>
                3. Which part was incorrect?{' '}
                <span style={{ fontWeight: 400, textTransform: 'none', color: 'var(--muted2)', fontSize: '0.74rem' }}>
                  (select all that apply)
                </span>
              </legend>
              <div className="fb-options">
                {WRONG_PART_LABELS.map(({ key, label }) => (
                  <label
                    key={key}
                    className={`fb-option${wrongParts[key] ? ' fb-option--selected' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={wrongParts[key]}
                      onChange={() => toggleWrongPart(key)}
                      style={{ accentColor: 'var(--red)' }}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {/* Comments */}
          <div className="fb-fieldset">
            <label htmlFor="fb-comments" className="form-label" style={{ marginBottom: '0.5rem', display: 'block' }}>
              {commentQ} Additional comments{' '}
              <span style={{ fontWeight: 400, textTransform: 'none', color: 'var(--muted2)', fontSize: '0.74rem' }}>(optional)</span>
            </label>
            <textarea
              id="fb-comments"
              rows={4}
              maxLength={MAX_CHARS}
              value={comments}
              onChange={e => setComments(e.target.value)}
              placeholder="Describe what was helpful or what could be improved…"
              className="form-input fb-textarea"
            />
            <div className="fb-char-count">
              <span style={{ color: comments.length >= MAX_CHARS ? 'var(--red)' : 'var(--muted2)' }}>
                {comments.length} / {MAX_CHARS}
              </span>
            </div>
          </div>

          {/* Error */}
          {error && <p className="fb-error">{error}</p>}

          {/* Actions */}
          <div className="fb-actions">
            <button type="button" onClick={onClose} className="fb-cancel-btn">Cancel</button>
            <button type="button" onClick={handleSubmit} className="btn-submit" style={{ marginTop: 0, width: 'auto', padding: '0.5rem 1.25rem', fontSize: '0.9rem' }}>
              Submit feedback
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
