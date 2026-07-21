import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminAuditLog from './AdminAuditLog'
import { fetchAuditLog, fetchAuditUsers, type AuditEntry } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, fetchAuditLog: vi.fn(), fetchAuditUsers: vi.fn() }
})

function entry(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 1, battery_id: 42, action: 'UPDATE', changed_by: 'admin',
    changed_at: new Date().toISOString(),
    old_values: { ah: 55, technology: 'MF', battery_code: 'NS60' },
    new_values: { ah: 60, technology: 'MF', battery_code: 'NS60' },
    ...overrides,
  }
}

function renderPage() {
  return render(<MemoryRouter><AdminAuditLog /></MemoryRouter>)
}

describe('AdminAuditLog', () => {
  beforeEach(() => {
    vi.mocked(fetchAuditLog).mockReset()
    vi.mocked(fetchAuditUsers).mockReset().mockResolvedValue({ users: ['admin', 'alice'] })
  })

  it('loads and renders audit entries with the action badge and battery code', async () => {
    vi.mocked(fetchAuditLog).mockResolvedValue({ items: [entry()], total: 1, page: 1 })
    renderPage()
    // 'UPDATE' also appears as a filter-chip button from first render, so
    // wait on the battery code (unique to the loaded row) instead.
    await waitFor(() => expect(screen.getByText('NS60')).toBeInTheDocument())
    expect(screen.getAllByText('UPDATE')).toHaveLength(2)
    // ah changed (55->60) but technology and battery_code did not -> 1 field changed
    expect(screen.getByText('1 field')).toBeInTheDocument()
  })

  it('shows "No audit entries found" when the page is empty', async () => {
    vi.mocked(fetchAuditLog).mockResolvedValue({ items: [], total: 0, page: 1 })
    renderPage()
    await waitFor(() => expect(screen.getByText('No audit entries found')).toBeInTheDocument())
  })

  it('shows an error message when the load fails', async () => {
    vi.mocked(fetchAuditLog).mockRejectedValue(new Error('Database unreachable'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Database unreachable')).toBeInTheDocument())
  })

  it('expands the diff viewer showing only the changed field highlighted, and collapses again', async () => {
    vi.mocked(fetchAuditLog).mockResolvedValue({ items: [entry()], total: 1, page: 1 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: /diff/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /diff/i }))

    expect(screen.getByText('55')).toBeInTheDocument()
    expect(screen.getByText('60')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide/i }))
    expect(screen.queryByText('55')).not.toBeInTheDocument()
  })

  it('applying an action filter re-fetches with the selected action and resets to page 1', async () => {
    vi.mocked(fetchAuditLog).mockResolvedValue({ items: [entry()], total: 1, page: 1 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(fetchAuditLog).toHaveBeenCalledWith(1, 50, {}))
    await user.click(screen.getByRole('button', { name: 'DELETE' }))
    await user.click(screen.getByRole('button', { name: 'Apply Filters' }))

    await waitFor(() => expect(fetchAuditLog).toHaveBeenLastCalledWith(1, 50, { action: 'DELETE' }))
    expect(screen.getByText('Filtered')).toBeInTheDocument()
  })

  it('Reset clears applied filters and re-fetches with none', async () => {
    vi.mocked(fetchAuditLog).mockResolvedValue({ items: [entry()], total: 1, page: 1 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(fetchAuditLog).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'INSERT' }))
    await user.click(screen.getByRole('button', { name: 'Apply Filters' }))
    await waitFor(() => expect(screen.getByText('Filtered')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: /reset/i }))
    await waitFor(() => expect(screen.queryByText('Filtered')).not.toBeInTheDocument())
    expect(fetchAuditLog).toHaveBeenLastCalledWith(1, 50, {})
  })

  it('paginates forward when there is more than one page', async () => {
    vi.mocked(fetchAuditLog)
      .mockResolvedValueOnce({ items: [entry()], total: 120, page: 1 })
      .mockResolvedValueOnce({ items: [entry({ id: 2 })], total: 120, page: 2 })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByText('1 / 3')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /next/i }))

    expect(fetchAuditLog).toHaveBeenLastCalledWith(2, 50, {})
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeInTheDocument())
  })
})
