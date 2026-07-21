import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminSearchLog from './AdminSearchLog'
import { fetchSearchEvents, type SearchEventEntry } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, fetchSearchEvents: vi.fn() }
})

function event(overrides: Partial<SearchEventEntry> = {}): SearchEventEntry {
  return {
    id: 1, timestamp: '2026-01-01T10:00:00Z', make: 'Toyota', model: 'Corolla', year: 2020,
    engine_cc: 1800, fuel_type: 'Petrol', battery_returned: 'NS60-MF', battery_ah: 60,
    match_type: 'Exact Match', confidence: 100, matched: true, ip_address: '1.2.3.4',
    input_type: 'select', ...overrides,
  }
}

function items(n: number): SearchEventEntry[] {
  return Array.from({ length: n }, (_, i) => event({ id: i + 1 }))
}

function renderPage() {
  return render(<MemoryRouter><AdminSearchLog /></MemoryRouter>)
}

describe('AdminSearchLog', () => {
  beforeEach(() => {
    vi.mocked(fetchSearchEvents).mockReset()
  })

  it('loads and renders search event rows', async () => {
    vi.mocked(fetchSearchEvents).mockResolvedValue({ items: items(2), total: 2, page: 1, page_size: 50 })
    renderPage()
    await waitFor(() => expect(screen.getAllByText('NS60-MF')).toHaveLength(2))
    expect(screen.getAllByText('Exact Match')).toHaveLength(2)
    expect(screen.getByText('2 searches recorded in total')).toBeInTheDocument()
  })

  it('shows the empty state when there are no events', async () => {
    vi.mocked(fetchSearchEvents).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
    renderPage()
    await waitFor(() => expect(screen.getByText('No searches recorded yet.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /download pdf/i })).toBeDisabled()
  })

  it('shows an error message when loading fails', async () => {
    vi.mocked(fetchSearchEvents).mockRejectedValue(new Error('boom'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Failed to load search events.')).toBeInTheDocument())
  })

  it('hides pagination when total fits on one page, and pages forward when it does not', async () => {
    vi.mocked(fetchSearchEvents).mockResolvedValueOnce({ items: items(2), total: 2, page: 1, page_size: 50 })
    renderPage()
    await waitFor(() => expect(screen.getAllByText('NS60-MF')).toHaveLength(2))
    expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument()
  })

  it('paginates forward and requests the next page from the API', async () => {
    vi.mocked(fetchSearchEvents)
      .mockResolvedValueOnce({ items: items(50), total: 120, page: 1, page_size: 50 })
      .mockResolvedValueOnce({ items: items(50), total: 120, page: 2, page_size: 50 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('Page 1 of 3 · 120 events')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /next/i }))

    expect(fetchSearchEvents).toHaveBeenCalledWith(2, 50)
    await waitFor(() => expect(screen.getByText('Page 2 of 3 · 120 events')).toBeInTheDocument())
  })
})
