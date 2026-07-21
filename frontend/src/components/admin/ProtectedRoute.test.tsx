import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ProtectedRoute } from './ProtectedRoute'
import { adminMe, AdminNetworkError } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, adminMe: vi.fn() }
})

function renderProtected() {
  return render(
    <MemoryRouter initialEntries={['/admin/dashboard']}>
      <Routes>
        <Route path="/admin/login" element={<div>Login Page</div>} />
        <Route path="/admin/dashboard" element={
          <ProtectedRoute><div>Secret Dashboard</div></ProtectedRoute>
        } />
      </Routes>
    </MemoryRouter>
  )
}

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.mocked(adminMe).mockReset()
  })

  it('renders nothing while the auth check is in flight', () => {
    vi.mocked(adminMe).mockReturnValue(new Promise(() => {}))
    const { container } = renderProtected()
    expect(container.textContent).toBe('')
  })

  it('renders the protected children once adminMe resolves', async () => {
    vi.mocked(adminMe).mockResolvedValue({ username: 'admin' })
    renderProtected()
    await waitFor(() => expect(screen.getByText('Secret Dashboard')).toBeInTheDocument())
  })

  it('redirects to /admin/login on an auth failure', async () => {
    vi.mocked(adminMe).mockRejectedValue(new Error('Not authenticated'))
    renderProtected()
    await waitFor(() => expect(screen.getByText('Login Page')).toBeInTheDocument())
  })

  it('shows a retry screen (not a login redirect) when the backend is unreachable', async () => {
    vi.mocked(adminMe).mockRejectedValue(new AdminNetworkError('down'))
    renderProtected()
    await waitFor(() => expect(screen.getByText('The server is temporarily unavailable')).toBeInTheDocument())
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
