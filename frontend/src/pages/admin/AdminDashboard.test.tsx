import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminDashboard from './AdminDashboard'
import {
  fetchAdminStats, fetchHealthStatus, refreshCache, getWebValidateCoverage, fetchBatteries,
  type AdminStats, type HealthStatus, type CoverageInfo,
} from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return {
    ...actual,
    fetchAdminStats: vi.fn(), fetchHealthStatus: vi.fn(), refreshCache: vi.fn(),
    getWebValidateCoverage: vi.fn(), fetchBatteries: vi.fn(),
  }
})

function stats(overrides: Partial<AdminStats['counts']> = {}): AdminStats {
  return {
    counts: {
      battery_specs: 500, vehicle_years: 10000, vehicle_years_total: 12000, vehicles_raw: 12000,
      model_aliases: 300, inference_makes: 20, inference_models: 100, inference_records: 5000,
      fitment_makes: 15, fitment_models: 80, fitment_records: 3000, vehicle_years_exide_pairs: 200,
      vehicle_years_exide_total: 250, battery_origin_local: 300, battery_origin_imported: 200,
      battery_tech_mf: 200, battery_tech_efb: 150, battery_tech_agm: 100, battery_tech_flooded: 50,
      ...overrides,
    },
    db_reads: 42, match_breakdown: { matched: 80, close: 15, fallback: 5, total: 100 },
  }
}
function health(overrides: Partial<HealthStatus> = {}): HealthStatus {
  return {
    status: 'ok', connected: true, latency_ms: 12, cluster_connections: 5, max_connections: 100,
    cluster_usage_pct: 5, pool_size: 10, pool_checked_out: 1, pool_usage_pct: 10,
    ...overrides,
  }
}
function coverage(overrides: Partial<CoverageInfo> = {}): CoverageInfo {
  return {
    total: 1000, matched: 900, unmatched: 100, pct_matched: 90, master_count: 800, staging_count: 0,
    unmatched_vehicles: [], by_make: [], total_buckets: 10, resolved_buckets: 9, remaining_buckets: 1,
    web_cache_size: 500, ...overrides,
  }
}

function renderPage() {
  return render(<MemoryRouter><AdminDashboard /></MemoryRouter>)
}

describe('AdminDashboard', () => {
  beforeEach(() => {
    vi.mocked(fetchAdminStats).mockReset()
    vi.mocked(fetchHealthStatus).mockReset()
    vi.mocked(refreshCache).mockReset()
    vi.mocked(getWebValidateCoverage).mockReset()
    vi.mocked(fetchBatteries).mockReset()
  })

  it('loads all dashboard data and renders the battery record total and health status', async () => {
    vi.mocked(fetchAdminStats).mockResolvedValue(stats())
    vi.mocked(fetchHealthStatus).mockResolvedValue(health())
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 500, page: 1, page_size: 200, items: [] })
    renderPage()

    await waitFor(() => expect(screen.getByText('500')).toBeInTheDocument())
    expect(screen.getByText('Database Health')).toBeInTheDocument()
    expect(screen.getByText('12 ms')).toBeInTheDocument()
  })

  it('shows an error message when the dashboard data fails to load', async () => {
    vi.mocked(fetchAdminStats).mockRejectedValue(new Error('Stats endpoint down'))
    vi.mocked(fetchHealthStatus).mockResolvedValue(health())
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 0, page: 1, page_size: 200, items: [] })
    renderPage()

    await waitFor(() => expect(screen.getByText('Stats endpoint down')).toBeInTheDocument())
  })

  it('the "Refresh now" button reloads all four data sources', async () => {
    vi.mocked(fetchAdminStats).mockResolvedValue(stats())
    vi.mocked(fetchHealthStatus).mockResolvedValue(health())
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 500, page: 1, page_size: 200, items: [] })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(fetchAdminStats).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: /refresh now/i }))
    await waitFor(() => expect(fetchAdminStats).toHaveBeenCalledTimes(2))
  })

  it('refreshing the matcher cache shows a success message', async () => {
    vi.mocked(fetchAdminStats).mockResolvedValue(stats())
    vi.mocked(fetchHealthStatus).mockResolvedValue(health())
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 500, page: 1, page_size: 200, items: [] })
    vi.mocked(refreshCache).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('Refresh Matcher Cache')).toBeInTheDocument())
    await user.click(screen.getByText('Refresh Matcher Cache'))

    await waitFor(() => expect(screen.getByText('Matcher cache refreshed successfully')).toBeInTheDocument())
  })

  it('shows a failure message when the cache refresh call fails', async () => {
    vi.mocked(fetchAdminStats).mockResolvedValue(stats())
    vi.mocked(fetchHealthStatus).mockResolvedValue(health())
    vi.mocked(getWebValidateCoverage).mockResolvedValue(coverage())
    vi.mocked(fetchBatteries).mockResolvedValue({ total: 500, page: 1, page_size: 200, items: [] })
    vi.mocked(refreshCache).mockRejectedValue(new Error('nope'))
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('Refresh Matcher Cache')).toBeInTheDocument())
    await user.click(screen.getByText('Refresh Matcher Cache'))

    await waitFor(() => expect(screen.getByText('Cache refresh failed')).toBeInTheDocument())
  })
})
