import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { VehicleFinderForm } from './VehicleFinderForm'
import * as api from '@/lib/api'
import type { RecommendationResult } from '@/types/battery'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    fetchMakes: vi.fn(),
    fetchModels: vi.fn(),
    fetchYears: vi.fn(),
    fetchRecommendation: vi.fn(),
    searchBatteryBySpecs: vi.fn(),
  }
})

function noop() {}

function renderForm() {
  return render(
    <VehicleFinderForm
      typeMode={false}
      onTypeModeChange={noop}
      onEstConfChange={noop}
    />
  )
}

function sampleResult(): RecommendationResult {
  return {
    make: 'Toyota', model: 'Corolla', year: 2020, engine_cc: 1800, fuel_type: 'PETROL',
    battery_region: 'NS', recommended_ah: 60, preferred_tech: 'MF', confidence: 100,
    match_type: 'exact', matched_make: 'Toyota', matched_model: 'Corolla', matched_year: 2020,
    primary: { battery_code: 'NS60-MF', model_key: 'NS60', ah: 60, cca_en: 480, technology: 'MF', origin: 'local' },
    alternatives: [],
  }
}

describe('VehicleFinderForm — select mode', () => {
  beforeEach(() => {
    vi.mocked(api.fetchMakes).mockResolvedValue(['Toyota', 'BMW'])
    vi.mocked(api.fetchModels).mockResolvedValue(['Corolla', 'Camry'])
    vi.mocked(api.fetchYears).mockResolvedValue([2019, 2020, 2021])
  })

  it('loads makes on mount and populates the make dropdown', async () => {
    renderForm()
    await waitFor(() => expect(screen.getByRole('option', { name: 'Toyota' })).toBeInTheDocument())
    expect(screen.getByRole('option', { name: 'BMW' })).toBeInTheDocument()
  })

  it('cascades make -> model -> year, disabling submit until all three are chosen', async () => {
    const user = userEvent.setup()
    renderForm()
    await waitFor(() => expect(screen.getByRole('option', { name: 'Toyota' })).toBeInTheDocument())

    const submitBtn = screen.getByRole('button', { name: /find battery/i })
    expect(submitBtn).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Car Make'), 'Toyota')
    expect(api.fetchModels).toHaveBeenCalledWith('Toyota')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Corolla' })).toBeInTheDocument())
    expect(submitBtn).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Model'), 'Corolla')
    expect(api.fetchYears).toHaveBeenCalledWith('Toyota', 'Corolla')
    await waitFor(() => expect(screen.getByRole('option', { name: '2020' })).toBeInTheDocument())
    expect(submitBtn).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Year'), '2020')
    expect(submitBtn).toBeEnabled()
  })

  it('submits the vehicle payload and renders the result card on success', async () => {
    vi.mocked(api.fetchRecommendation).mockResolvedValue(sampleResult())
    const user = userEvent.setup()
    renderForm()
    await waitFor(() => expect(screen.getByRole('option', { name: 'Toyota' })).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText('Car Make'), 'Toyota')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Corolla' })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Model'), 'Corolla')
    await waitFor(() => expect(screen.getByRole('option', { name: '2020' })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Year'), '2020')

    await user.click(screen.getByRole('button', { name: /find battery/i }))

    expect(api.fetchRecommendation).toHaveBeenCalledWith(expect.objectContaining({
      make: 'Toyota', model: 'Corolla', year: 2020, input_type: 'select', stop_start: true,
    }))
    await waitFor(() => expect(screen.getByText('Battery Recommendation')).toBeInTheDocument())
    expect(screen.getByText('NS60-MF')).toBeInTheDocument()
  })

  it('shows a friendly error message and no result card when the recommendation request fails', async () => {
    vi.mocked(api.fetchRecommendation).mockRejectedValue(new Error('HTTP 404'))
    const user = userEvent.setup()
    renderForm()
    await waitFor(() => expect(screen.getByRole('option', { name: 'Toyota' })).toBeInTheDocument())

    await user.selectOptions(screen.getByLabelText('Car Make'), 'Toyota')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Corolla' })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Model'), 'Corolla')
    await waitFor(() => expect(screen.getByRole('option', { name: '2020' })).toBeInTheDocument())
    await user.selectOptions(screen.getByLabelText('Year'), '2020')
    await user.click(screen.getByRole('button', { name: /find battery/i }))

    // Both the toast and the inline error-block show the same message.
    await waitFor(() => expect(screen.getAllByText('No data found for the selected vehicle.').length).toBeGreaterThan(0))
    expect(screen.queryByText('Battery Recommendation')).not.toBeInTheDocument()
  })

  it('shows a friendly error inline (not a crash) when the initial makes fetch fails', async () => {
    vi.mocked(api.fetchMakes).mockReset().mockRejectedValue(new TypeError('Failed to fetch'))
    renderForm()
    await waitFor(() =>
      expect(screen.getByText('No internet connection. Please check your network and try again.')).toBeInTheDocument()
    )
  })
})
