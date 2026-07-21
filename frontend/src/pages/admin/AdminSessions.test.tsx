import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminSessions from './AdminSessions'
import { fetchSessions, revokeSession, AdminAuthError, type SessionEntry } from '@/lib/adminApi'

const navigateMock = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, fetchSessions: vi.fn(), revokeSession: vi.fn() }
})

function session(overrides: Partial<SessionEntry> = {}): SessionEntry {
  return { id: 1, created_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-01T08:00:00Z', ip_address: '1.2.3.4', expired: false, ...overrides }
}

function renderPage() {
  return render(<MemoryRouter><AdminSessions /></MemoryRouter>)
}

describe('AdminSessions', () => {
  beforeEach(() => {
    navigateMock.mockReset()
    vi.mocked(fetchSessions).mockReset()
    vi.mocked(revokeSession).mockReset()
  })

  it('loads and displays active vs expired session counts', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      sessions: [session({ id: 1, expired: false }), session({ id: 2, expired: false }), session({ id: 3, expired: true })],
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('2', { selector: 'div' })).toBeInTheDocument())
    expect(screen.getByText('1', { selector: 'div' })).toBeInTheDocument()
    expect(screen.getAllByText('1.2.3.4')).toHaveLength(3)
  })

  it('shows "No sessions found" when there are none', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({ sessions: [] })
    renderPage()
    await waitFor(() => expect(screen.getByText('No sessions found')).toBeInTheDocument())
  })

  it('redirects to login on an auth failure while loading', async () => {
    vi.mocked(fetchSessions).mockRejectedValue(new AdminAuthError())
    renderPage()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/admin/login', { replace: true }))
  })

  it('shows a plain error message for a non-auth load failure', async () => {
    vi.mocked(fetchSessions).mockRejectedValue(new Error('Database unavailable'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Database unavailable')).toBeInTheDocument())
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('revokes an active session and reloads the list', async () => {
    vi.mocked(fetchSessions)
      .mockResolvedValueOnce({ sessions: [session({ id: 1, expired: false })] })
      .mockResolvedValueOnce({ sessions: [session({ id: 1, expired: true })] })
    vi.mocked(revokeSession).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Revoke' }))

    expect(revokeSession).toHaveBeenCalledWith(1)
    await waitFor(() => expect(fetchSessions).toHaveBeenCalledTimes(2))
  })
})
