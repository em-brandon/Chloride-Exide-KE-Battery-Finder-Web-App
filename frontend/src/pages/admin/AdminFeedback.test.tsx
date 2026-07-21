import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminFeedback from './AdminFeedback'
import {
  fetchFeedback, fetchFeedbackSummary, downloadFeedbackPdf, downloadFeedbackCsv,
  type FeedbackEntry, type FeedbackSummary,
} from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return {
    ...actual,
    fetchFeedback: vi.fn(), fetchFeedbackSummary: vi.fn(),
    downloadFeedbackPdf: vi.fn(), downloadFeedbackCsv: vi.fn(),
  }
})

function feedback(overrides: Partial<FeedbackEntry> = {}): FeedbackEntry {
  return {
    id: 1, vehicle_label: 'Toyota Corolla 2020', satisfaction: 4, accuracy: 'exact',
    wrong_parts: null, comments: null, submitted_at: new Date().toISOString(),
    ip_address: null, test_username: null, input_type: 'select',
    match_confidence: 95, match_type: 'exact_match', recommended_battery: 'NS60-MF',
    ...overrides,
  }
}
function summary(overrides: Partial<FeedbackSummary> = {}): FeedbackSummary {
  return { total: 10, avg_satisfaction: 4.2, accuracy_breakdown: { exact: 8, close: 2 }, star_breakdown: { '5': 5, '4': 3, '3': 2 }, ...overrides }
}

function renderPage() {
  return render(<MemoryRouter><AdminFeedback /></MemoryRouter>)
}

describe('AdminFeedback', () => {
  beforeEach(() => {
    vi.mocked(fetchFeedback).mockReset()
    vi.mocked(fetchFeedbackSummary).mockReset()
    vi.mocked(downloadFeedbackPdf).mockReset()
    vi.mocked(downloadFeedbackCsv).mockReset()
  })

  it('loads page 1 with the summary strip, and renders a feedback row', async () => {
    vi.mocked(fetchFeedback).mockResolvedValue({ items: [feedback()], total: 1, page: 1, page_size: 25 })
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary())
    renderPage()
    await waitFor(() => expect(screen.getByText('Toyota Corolla 2020')).toBeInTheDocument())
    expect(screen.getByText('10')).toBeInTheDocument() // total responses
    expect(screen.getByText('NS60-MF')).toBeInTheDocument()
  })

  it('shows the empty state when there is no feedback', async () => {
    vi.mocked(fetchFeedback).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 })
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary({ total: 0 }))
    renderPage()
    await waitFor(() => expect(screen.getByText('No feedback entries found.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /export csv/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /export pdf/i })).toBeDisabled()
  })

  it('shows an error message when loading fails', async () => {
    vi.mocked(fetchFeedback).mockRejectedValue(new Error('Server error'))
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary())
    renderPage()
    await waitFor(() => expect(screen.getByText('Server error')).toBeInTheDocument())
  })

  it('changing the accuracy filter reloads page 1 with that filter and hides the summary strip', async () => {
    vi.mocked(fetchFeedback).mockResolvedValue({ items: [feedback()], total: 1, page: 1, page_size: 25 })
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary())
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(fetchFeedback).toHaveBeenCalledWith(1, 25, undefined))
    await user.selectOptions(screen.getByDisplayValue('All accuracy'), 'wrong')

    await waitFor(() => expect(fetchFeedback).toHaveBeenLastCalledWith(1, 25, 'wrong'))
    // Summary strip's TOTAL RESPONSES card is hidden once a filter is active.
    expect(screen.queryByText('TOTAL RESPONSES')).not.toBeInTheDocument()
  })

  it('exports CSV with the current accuracy filter applied', async () => {
    vi.mocked(fetchFeedback).mockResolvedValue({ items: [feedback()], total: 1, page: 1, page_size: 25 })
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary())
    vi.mocked(downloadFeedbackCsv).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: /export csv/i })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /export csv/i }))
    expect(downloadFeedbackCsv).toHaveBeenCalledWith(undefined)
  })

  it('paginates forward, requesting the next page', async () => {
    vi.mocked(fetchFeedback)
      .mockResolvedValueOnce({ items: [feedback()], total: 30, page: 1, page_size: 25 })
      .mockResolvedValueOnce({ items: [feedback({ id: 2 })], total: 30, page: 2, page_size: 25 })
    vi.mocked(fetchFeedbackSummary).mockResolvedValue(summary({ total: 30 }))
    const user = userEvent.setup()
    const { container } = renderPage()

    await waitFor(() => expect(screen.getByText(/page 1 of 2/)).toBeInTheDocument())
    // Prev/Next are icon-only buttons with no accessible name — select the
    // second (Next) of the two pagination buttons by DOM order instead.
    const paginationButtons = container.querySelectorAll('button')
    const nextButton = paginationButtons[paginationButtons.length - 1]
    await user.click(nextButton)

    expect(fetchFeedback).toHaveBeenLastCalledWith(2, 25, undefined)
    await waitFor(() => expect(screen.getByText(/page 2 of 2/)).toBeInTheDocument())
  })
})
