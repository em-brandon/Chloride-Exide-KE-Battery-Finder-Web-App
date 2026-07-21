import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminLogin from './AdminLogin'
import { adminLogin } from '@/lib/adminApi'

const navigateMock = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, adminLogin: vi.fn() }
})

// The username/password <label>s aren't htmlFor-associated with their
// inputs, so getByLabelText can't find them — query by type instead.
function fields(container: HTMLElement) {
  return {
    username: container.querySelector('input[type="text"]') as HTMLInputElement,
    password: container.querySelector('input[type="password"]') as HTMLInputElement,
  }
}

describe('AdminLogin', () => {
  beforeEach(() => {
    navigateMock.mockReset()
    vi.mocked(adminLogin).mockReset()
  })

  it('submits the entered username/password and navigates to the dashboard on success', async () => {
    vi.mocked(adminLogin).mockResolvedValue(undefined)
    const user = userEvent.setup()
    const { container } = render(<MemoryRouter><AdminLogin /></MemoryRouter>)
    const { username, password } = fields(container)

    await user.type(username, 'admin')
    await user.type(password, 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(adminLogin).toHaveBeenCalledWith('admin', 'secret')
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/admin/dashboard', { replace: true }))
  })

  it('shows the error message and does not navigate on a failed login', async () => {
    vi.mocked(adminLogin).mockRejectedValue(new Error('Invalid credentials'))
    const user = userEvent.setup()
    const { container } = render(<MemoryRouter><AdminLogin /></MemoryRouter>)
    const { username, password } = fields(container)

    await user.type(username, 'admin')
    await user.type(password, 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => expect(screen.getByText('Invalid credentials')).toBeInTheDocument())
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('disables the submit button and shows "Signing in…" while the request is in flight', async () => {
    let resolveLogin!: () => void
    vi.mocked(adminLogin).mockReturnValue(new Promise(resolve => { resolveLogin = () => resolve(undefined) }))
    const user = userEvent.setup()
    const { container } = render(<MemoryRouter><AdminLogin /></MemoryRouter>)
    const { username, password } = fields(container)

    await user.type(username, 'admin')
    await user.type(password, 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(screen.getByRole('button', { name: /signing in/i })).toBeDisabled()
    resolveLogin()
    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
  })
})
