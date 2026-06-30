/**
 * FeedbackModal.tsx
 *
 * Left-side slide-in feedback panel styled with the app's CSS variable system.
 * Submits user feedback to POST /api/feedback.
 */

import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { submitFeedback } from '@/lib/api'
import { useTestUser } from '@/lib/TestUserContext'
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

interface FeedbackModalProps {
  open: boolean
  onClose: () => void
  vehicleLabel: string          // e.g. "Toyota Camry 2020"
  inputType?: string            // 'select' | 'type'
  matchConfidence?: number      // 0-100
  matchType?: string            // e.g. 'exact_match'
  recommendedBattery?: string   // primary battery code returned
  darkMode?: boolean
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

export function FeedbackModal({ open, onClose, vehicleLabel, inputType, matchConfidence, matchType, recommendedBattery, darkMode = false }: FeedbackModalProps) {
  const { user } = useTestUser()
  const [satisfaction, setSatisfaction] = useState(0)
  const [accuracy, setAccuracy]         = useState<Accuracy>('')
  const [wrongParts, setWrongParts]     = useState<WrongPart>(BLANK_WRONG)
  const [wrongPartsError, setWrongPartsError] = useState(false)
  const [comments, setComments]         = useState('')
  const [submitted, setSubmitted]       = useState(false)
  const [submitting, setSubmitting]     = useState(false)
  const [error, setError]               = useState('')

  // Reset state when panel reopens
  useEffect(() => {
    if (open) {
      setSatisfaction(0)
      setAccuracy('')
      setWrongParts(BLANK_WRONG)
      setWrongPartsError(false)
      setComments('')
      setSubmitted(false)
      setSubmitting(false)
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
    setWrongParts(prev => {
      const next = { ...prev, [key]: !prev[key] }
      if (Object.values(next).some(Boolean)) setWrongPartsError(false)
      return next
    })
  }

  async function handleSubmit() {
    if (satisfaction === 0) {
      setError('Please rate your satisfaction before submitting.')
      return
    }
    if (!accuracy) {
      setError('Please select an accuracy option before submitting.')
      return
    }
    if (accuracy === 'wrong' || accuracy === 'close') {
      const anyChecked = Object.values(wrongParts).some(Boolean)
      if (!anyChecked) {
        setWrongPartsError(true)
        setError('Please select at least one incorrect part (Q3) before submitting.')
        return
      }
    }
    setSubmitting(true)
    setError('')
    try {
      await submitFeedback({
        vehicle_label: vehicleLabel,
        satisfaction,
        accuracy,
        wrong_parts: wrongParts as unknown as { [key: string]: boolean },
        comments: comments.trim(),
        submitted_at: new Date().toISOString(),
        input_type: inputType,
        match_confidence: matchConfidence,
        match_type: matchType,
        recommended_battery: recommendedBattery,
      })
      setSubmitted(true)
    } catch {
      setError('Failed to submit feedback. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const commentQ = (accuracy === 'close' || accuracy === 'wrong') ? '4.' : '3.'

  const drawer = (
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

          {/* Identity badge */}
          {user ? (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem', borderRadius: 8, padding: '0.35rem 0.7rem', marginBottom: '0.25rem',
              color:      darkMode ? '#4ade80'                   : '#15803d',
              background: darkMode ? 'rgba(74,222,128,0.1)'     : '#f0fdf4',
              border:     `1px solid ${darkMode ? 'rgba(74,222,128,0.25)' : '#bbf7d0'}`,
            }}>
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd"/></svg>
              Submitting as <strong style={{ marginLeft: 2 }}>{user.username}</strong>
            </div>
          ) : (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem', borderRadius: 8, padding: '0.35rem 0.7rem', marginBottom: '0.25rem',
              color:      darkMode ? 'rgba(229,231,235,0.6)' : '#6b7280',
              background: darkMode ? '#252836'               : '#f9fafb',
              border:     `1px solid ${darkMode ? '#3a3f55' : '#e2e4e9'}`,
            }}>
              Submitting anonymously —{' '}
              <a href="/login" target="_blank" rel="noopener noreferrer" style={{ color: '#CC0000', fontWeight: 600, textDecoration: 'none' }}>
                Sign in
              </a>{' '}to link your feedback
            </div>
          )}

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
            <fieldset
              className="fb-fieldset"
              style={wrongPartsError ? { border: '1px solid #dc2626', borderRadius: 8, padding: '0.5rem', background: darkMode ? 'rgba(220,38,38,0.12)' : '#fef2f2' } : undefined}
            >
              <legend className="form-label" style={{ marginBottom: '0.5rem' }}>
                3. Which part was incorrect?{' '}
                <span style={{ color: '#dc2626', fontWeight: 700 }}>*</span>{' '}
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
            <button type="button" onClick={onClose} className="fb-cancel-btn" disabled={submitting}>Cancel</button>
            <button type="button" onClick={handleSubmit} className="btn-submit" disabled={submitting} style={{ marginTop: 0, width: 'auto', padding: '0.5rem 1.25rem', fontSize: '0.9rem' }}>
              {submitting ? 'Submitting…' : 'Submit feedback'}
            </button>
          </div>
        </div>
      )}
    </div>
  )

  const darkVars: React.CSSProperties = {
    '--text':     'rgba(229, 231, 235, 0.95)',
    '--border':   '#2a2d3a',
    '--bg':       '#1a1d26',
    '--card-bg':  '#252836',
    '--card-bg2': '#1a1d26',
    '--muted':    '#6b7280',
    '--muted2':   'rgba(229,231,235,0.4)',
  } as React.CSSProperties

  return createPortal(
    darkMode
      ? <div className="page-dark" style={darkVars}>{drawer}</div>
      : drawer,
    document.body
  )
}
