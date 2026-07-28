import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminVehicleData from './AdminVehicleData'
import {
  getWebValidateCoverage, getPipelineStaleness, getVehicleDataOemFitment, getVehicleDataOemFitmentByMake,
  type CoverageInfo, type OemFitmentRow, type OemFitmentMakeStat,
} from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return {
    ...actual,
    getWebValidateCoverage: vi.fn(), getPipelineStaleness: vi.fn(),
    getWebValidateMatched: vi.fn(), getVehicleDataOemFitment: vi.fn(),
    getVehicleDataOemFitmentByMake: vi.fn(),
  }
})

function coverage(overrides: Partial<CoverageInfo> = {}): CoverageInfo {
  return {
    total: 1000, matched: 850, unmatched: 150, pct_matched: 85, master_count: 800,
    staging_count: 0, unmatched_vehicles: [], by_make: [
      { make: 'Toyota', total: 400, matched: 380, pct_matched: 95 },
      { make: 'BMW', total: 100, matched: 40, pct_matched: 40 },
    ],
    total_buckets: 50, resolved_buckets: 42, remaining_buckets: 8, web_cache_size: 1200,
    ...overrides,
  }
}
function fitmentRow(overrides: Partial<OemFitmentRow> = {}): OemFitmentRow {
  return {
    id: 1, vehicle_category: 'car', make: 'TOYOTA', model: 'COROLLA', year_from: 2015, year_to: 2020,
    ah: 60, technology: 'MF', raw_technology: 'MF', dimensions: '230x170x200', cylinder_capacity_cc: 1800,
    ...overrides,
  }
}
function makeStat(overrides: Partial<OemFitmentMakeStat> = {}): OemFitmentMakeStat {
  return { make: 'TOYOTA', model_count: 10, row_count: 20, year_min: 2000, year_max: 2020, ...overrides }
}

function renderPage() {
  return render(<MemoryRouter><AdminVehicleData /></MemoryRouter>)
}

describe('AdminVehicleData — Coverage tab', () => {
  beforeEach(() => {
    vi.mocked(getWebValidateCoverage).mockReset()
    vi.mocked(getPipelineStaleness).mockReset()
    vi.mocked(getVehicleDataOemFitment).mockReset().mockResolvedValue({ total: 0, page: 1, page_size: 50, items: [] })
  })

  it('loads and shows the matched percentage and combo counts', async () => {
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(getPipelineStaleness).mockResolvedValue({ stale: false, vehicles_last_updated_at: null, new_vehicles_since_last_run: 0 })
    renderPage()
    await waitFor(() => expect(screen.getByText('85.0%')).toBeInTheDocument())
    expect(screen.getByText('850 / 1,000 combos matched')).toBeInTheDocument()
  })

  it('shows the staleness banner when the dataset is stale', async () => {
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(getPipelineStaleness).mockResolvedValue({ stale: true, vehicles_last_updated_at: null, new_vehicles_since_last_run: 12 })
    renderPage()
    await waitFor(() => expect(screen.getByText(/12 new vehicle combos added/)).toBeInTheDocument())
  })

  it('shows an error message when the coverage load fails', async () => {
    vi.mocked(getWebValidateCoverage).mockRejectedValue(new Error('boom'))
    vi.mocked(getPipelineStaleness).mockResolvedValue({ stale: false, vehicles_last_updated_at: null, new_vehicles_since_last_run: 0 })
    renderPage()
    await waitFor(() => expect(screen.getByText('Failed to load coverage data.')).toBeInTheDocument())
  })

  it('filters the coverage-by-make table by search', async () => {
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(getPipelineStaleness).mockResolvedValue({ stale: false, vehicles_last_updated_at: null, new_vehicles_since_last_run: 0 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('Toyota')).toBeInTheDocument())
    expect(screen.getByText('BMW')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('Search make…'), 'bmw')
    expect(screen.queryByText('Toyota')).not.toBeInTheDocument()
    expect(screen.getByText('BMW')).toBeInTheDocument()
  })
})

describe('AdminVehicleData — OEM Fitment tab (brand grid)', () => {
  beforeEach(() => {
    vi.mocked(getWebValidateCoverage).mockReset().mockResolvedValue(coverage())
    vi.mocked(getPipelineStaleness).mockReset().mockResolvedValue({ stale: false, vehicles_last_updated_at: null, new_vehicles_since_last_run: 0 })
    vi.mocked(getVehicleDataOemFitment).mockReset()
    vi.mocked(getVehicleDataOemFitmentByMake).mockReset()
  })

  it('renders one tile per make from the by-make endpoint', async () => {
    vi.mocked(getVehicleDataOemFitmentByMake).mockResolvedValue({
      makes: [makeStat({ make: 'TOYOTA' }), makeStat({ make: 'HONDA', model_count: 5, row_count: 8 })],
    })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('OEM Fitment')).toBeInTheDocument())
    await user.click(screen.getByText('OEM Fitment'))

    await waitFor(() => expect(screen.getByText('TOYOTA')).toBeInTheDocument())
    expect(screen.getByText('HONDA')).toBeInTheDocument()
  })

  it('expands a tile to show that make\'s fitment rows, and collapses on second click', async () => {
    vi.mocked(getVehicleDataOemFitmentByMake).mockResolvedValue({ makes: [makeStat({ make: 'TOYOTA' })] })
    vi.mocked(getVehicleDataOemFitment).mockResolvedValue({ total: 1, page: 1, page_size: 50, items: [fitmentRow()] })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByText('OEM Fitment'))
    await waitFor(() => expect(screen.getByText('TOYOTA')).toBeInTheDocument())

    await user.click(screen.getByText('TOYOTA'))
    await waitFor(() => expect(screen.getByText('COROLLA')).toBeInTheDocument())
    expect(getVehicleDataOemFitment).toHaveBeenCalledWith(1, 50, '', 'TOYOTA')

    // 'TOYOTA' now appears twice (grid tile + expanded panel header) — click the tile (first match).
    await user.click(screen.getAllByText('TOYOTA')[0])
    await waitFor(() => expect(screen.queryByText('COROLLA')).not.toBeInTheDocument())
  })

  it('switches directly from one expanded make to another', async () => {
    vi.mocked(getVehicleDataOemFitmentByMake).mockResolvedValue({
      makes: [makeStat({ make: 'TOYOTA' }), makeStat({ make: 'HONDA' })],
    })
    vi.mocked(getVehicleDataOemFitment).mockImplementation(async (_p, _ps, _s, make) => ({
      total: 1, page: 1, page_size: 50,
      items: [fitmentRow({ make: make as string, model: make === 'HONDA' ? 'CIVIC' : 'COROLLA' })],
    }))
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByText('OEM Fitment'))
    await waitFor(() => expect(screen.getByText('TOYOTA')).toBeInTheDocument())

    await user.click(screen.getByText('TOYOTA'))
    await waitFor(() => expect(screen.getByText('COROLLA')).toBeInTheDocument())

    await user.click(screen.getByText('HONDA'))
    await waitFor(() => expect(screen.getByText('CIVIC')).toBeInTheDocument())
    expect(screen.queryByText('COROLLA')).not.toBeInTheDocument()
  })

  it('shows "No rows." when the expanded make has no fitment rows', async () => {
    vi.mocked(getVehicleDataOemFitmentByMake).mockResolvedValue({ makes: [makeStat({ make: 'TOYOTA' })] })
    vi.mocked(getVehicleDataOemFitment).mockResolvedValue({ total: 0, page: 1, page_size: 50, items: [] })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByText('OEM Fitment'))
    await waitFor(() => expect(screen.getByText('TOYOTA')).toBeInTheDocument())
    await user.click(screen.getByText('TOYOTA'))

    await waitFor(() => expect(screen.getByText('No rows.')).toBeInTheDocument())
  })

  it('filters the visible tiles via the grid search box', async () => {
    vi.mocked(getVehicleDataOemFitmentByMake).mockResolvedValue({
      makes: [makeStat({ make: 'TOYOTA' }), makeStat({ make: 'HONDA' })],
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByText('OEM Fitment'))
    await waitFor(() => expect(screen.getByText('TOYOTA')).toBeInTheDocument())
    expect(screen.getByText('HONDA')).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('Filter makes…'), 'toy')
    await waitFor(() => expect(screen.queryByText('HONDA')).not.toBeInTheDocument())
    expect(screen.getByText('TOYOTA')).toBeInTheDocument()
  })
})
