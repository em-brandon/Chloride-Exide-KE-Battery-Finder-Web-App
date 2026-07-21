import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminTestSessions from './AdminTestSessions'
import {
  fetchTestSessions, fetchTestUsers, revokeTestSession, AdminAuthError,
  type TestSessionEntry, type TestUserEntry,
} from '@/lib/adminApi'

const navigateMock = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, fetchTestSessions: vi.fn(), fetchTestUsers: vi.fn(), revokeTestSession: vi.fn() }
})

function sessionEntry(overrides: Partial<TestSessionEntry> = {}): TestSessionEntry {
  return {
    id: 1, username: 'brandon', user_id: 1, created_at: '2026-01-01T00:00:00Z',
    expires_at: '2026-01-02T00:00:00Z', last_seen_at: null, ip_address: '1.2.3.4',
    user_agent: null, expired: false, ...overrides,
  }
}
function userEntry(overrides: Partial<TestUserEntry> = {}): TestUserEntry {
  return { id: 1, username: 'brandon', email: 'b@example.com', created_at: '2026-01-01T00:00:00Z', is_active: true, active_sessions: 1, ...overrides }
}

function renderPage() {
  return render(<MemoryRouter><AdminTestSessions /></MemoryRouter>)
}

describe('AdminTestSessions', () => {
  beforeEach(() => {
    navigateMock.mockReset()
    vi.mocked(fetchTestSessions).mockReset()
    vi.mocked(fetchTestUsers).mockReset()
    vi.mocked(revokeTestSession).mockReset()
  })

  it('loads both sessions and users, showing the active session count in the header chip', async () => {
    vi.mocked(fetchTestSessions).mockResolvedValue({ sessions: [sessionEntry()] })
    vi.mocked(fetchTestUsers).mockResolvedValue({ users: [userEntry()] })
    renderPage()
    await waitFor(() => expect(screen.getByText('1 active session')).toBeInTheDocument())
    expect(screen.getByText('1 user')).toBeInTheDocument()
  })

  it('shows "No active sessions" when there are none, and hides the expired section entirely', async () => {
    vi.mocked(fetchTestSessions).mockResolvedValue({ sessions: [] })
    vi.mocked(fetchTestUsers).mockResolvedValue({ users: [] })
    renderPage()
    await waitFor(() => expect(screen.getByText('No active sessions')).toBeInTheDocument())
    expect(screen.queryByText(/^Expired/)).not.toBeInTheDocument()
  })

  it('switches to the Users tab and renders the user table', async () => {
    vi.mocked(fetchTestSessions).mockResolvedValue({ sessions: [] })
    vi.mocked(fetchTestUsers).mockResolvedValue({ users: [userEntry({ username: 'alice', active_sessions: 0, is_active: false })] })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: /Users \(1\)/ })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /Users \(1\)/ }))

    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('revokes an active test session and reloads', async () => {
    vi.mocked(fetchTestSessions)
      .mockResolvedValueOnce({ sessions: [sessionEntry()] })
      .mockResolvedValueOnce({ sessions: [sessionEntry({ expired: true })] })
    vi.mocked(fetchTestUsers).mockResolvedValue({ users: [] })
    vi.mocked(revokeTestSession).mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Revoke' }))

    expect(revokeTestSession).toHaveBeenCalledWith(1)
    await waitFor(() => expect(fetchTestSessions).toHaveBeenCalledTimes(2))
  })

  it('redirects to login on an AdminAuthError while loading', async () => {
    vi.mocked(fetchTestSessions).mockRejectedValue(new AdminAuthError())
    vi.mocked(fetchTestUsers).mockResolvedValue({ users: [] })
    renderPage()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/admin/login', { replace: true }))
  })
})
