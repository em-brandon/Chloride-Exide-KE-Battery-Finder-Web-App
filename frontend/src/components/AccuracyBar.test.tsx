import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AccuracyBar } from './AccuracyBar'
import type { RecommendationResult } from '@/types/battery'

function result(overrides: Partial<RecommendationResult> = {}): RecommendationResult {
  return {
    make: 'Toyota',
    model: 'Corolla',
    year: 2020,
    engine_cc: 1800,
    fuel_type: 'PETROL',
    battery_region: 'NS',
    recommended_ah: 60,
    preferred_tech: 'MF',
    confidence: 100,
    match_type: 'exact',
    matched_make: 'Toyota',
    matched_model: 'Corolla',
    matched_year: 2020,
    primary: { battery_code: 'X1', model_key: 'X1', ah: 60, cca_en: null, technology: 'MF', origin: 'local' },
    alternatives: [],
    ...overrides,
  }
}

describe('AccuracyBar', () => {
  it('scores an exact match with a matching year at 97% (50 model + 25 year + 12 source + 10 specs)', () => {
    render(<AccuracyBar data={result()} />)
    expect(screen.getByText('97%')).toBeInTheDocument()
  })

  it('scores a close match with a 2-year gap lower, reflecting the partial credit', () => {
    render(<AccuracyBar data={result({
      match_type: 'close', confidence: 75, matched_year: 2018, engine_cc: 2000,
    })} />)
    // model: round(20 + ((75-60)/29)*20) = 30, year(delta=2): 13, source(hasModel): 12, specs(hasModel): 10 = 65
    expect(screen.getByText('65%')).toBeInTheDocument()
  })

  it('scores an unmatched rule-based fallback at the low end', () => {
    render(<AccuracyBar data={result({
      match_type: 'fallback', confidence: 45, matched_make: null, matched_model: null, matched_year: null, engine_cc: 1500,
    })} />)
    // model: 0, year: 0 (no matched_year), source: 4 (no model), specs: 2 (no model, engine_cc guessed default) = 6
    expect(screen.getByText('6%')).toBeInTheDocument()
  })

  it('hides the factor labels and shows the info toggle in compact mode', () => {
    render(<AccuracyBar data={result()} compact />)
    expect(screen.queryByText('Car Found')).not.toBeInTheDocument()
    expect(screen.getByLabelText('About result accuracy')).toBeInTheDocument()
  })

  it('shows factor labels and no info toggle in the default (non-compact) mode', () => {
    render(<AccuracyBar data={result()} />)
    expect(screen.getByText('Car Found')).toBeInTheDocument()
    expect(screen.queryByLabelText('About result accuracy')).not.toBeInTheDocument()
  })

  it('toggles the explanatory tooltip open and closed in compact mode', async () => {
    const user = userEvent.setup()
    render(<AccuracyBar data={result()} compact />)
    expect(screen.queryByText('Result Accuracy bar')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('About result accuracy'))
    expect(screen.getByText('Result Accuracy bar')).toBeInTheDocument()

    await user.click(screen.getByLabelText('About result accuracy'))
    expect(screen.queryByText('Result Accuracy bar')).not.toBeInTheDocument()
  })
})
